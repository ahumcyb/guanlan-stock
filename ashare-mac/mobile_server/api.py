"""Bounded JSON API behind an HTTPS reverse proxy; no engine imports in web process."""
import argparse
import hashlib
import hmac
import json
import os
import re
import time
import threading
from http.server import BaseHTTPRequestHandler,HTTPServer
from socketserver import ThreadingMixIn
from pathlib import Path
from urllib.parse import urlsplit

from .artifacts import STRATEGIES,GENERATION,CODE,MAX_REPORT,MAX_CHART,atomic_json,checked_file,current_manifest
from .queue import JobQueue,canonical_uuid
from .realtime import RealtimeStore


class Failure(Exception):
    def __init__(self,status,code,message):self.status=status;self.code=code;self.message=message


class Service:
    def __init__(self,root,token,worker_token=None):
        if not re.fullmatch(r'[a-f0-9]{64}',token):raise ValueError('Invalid API credential')
        if worker_token is not None and (not re.fullmatch(r'[a-f0-9]{64}',worker_token) or worker_token==token):raise ValueError('Invalid worker credential')
        self.root=root.resolve();self.token=token;self.jobs=self.root/'jobs';self.jobs.mkdir(parents=True,exist_ok=True)
        self.worker_token=worker_token;self.queue=JobQueue(self.jobs)
        self.realtime=RealtimeStore(self.root)

    def state(self):
        return self.queue.public()

    def authorized_worker(self,authorization):
        return self.worker_token is not None and hmac.compare_digest(authorization.encode(),('Bearer '+self.worker_token).encode())

    def upload(self,path,authorization,lease,stream,length):
        if not self.authorized_worker(authorization):raise Failure(401,'UNAUTHORIZED','Worker authentication required')
        match=re.fullmatch(r'/v1/worker/uploads/([a-f0-9-]{36})',path)
        if not match or not canonical_uuid(match[1]) or not re.fullmatch(r'[a-f0-9]{64}',lease) or not 0<length<=256*1024*1024:raise Failure(400,'INVALID_UPLOAD','Invalid upload')
        job_id=match[1]
        state=self.queue.state()
        if state['status']!='running' or not self.queue.owns(state,job_id,lease):raise Failure(409,'LEASE_EXPIRED','Execution lease expired')
        incoming=self.root/'incoming';incoming.mkdir(exist_ok=True)
        temporary=incoming/('.upload-'+os.urandom(8).hex());destination=incoming/(job_id+'-'+lease+'.zip')
        digest=hashlib.sha256();remaining=length
        try:
            with temporary.open('xb') as output:
                while remaining:
                    chunk=stream.read(min(1024*1024,remaining))
                    if not chunk:raise Failure(400,'INCOMPLETE_UPLOAD','Incomplete upload')
                    output.write(chunk);digest.update(chunk);remaining-=len(chunk)
            if not self.queue.uploaded(job_id,lease,digest.hexdigest(),length,temporary,destination):
                raise Failure(409,'LEASE_EXPIRED','Execution lease expired')
            return 202,self.queue.public()
        finally:
            if temporary.exists():temporary.unlink()

    def dispatch(self,method,target,authorization,body=b''):
        if target=='/health' and method=='GET':return 200,{'status':'ok'}
        worker=target.startswith('/v1/worker/')
        if not (self.authorized_worker(authorization) if worker else hmac.compare_digest(authorization.encode(),('Bearer '+self.token).encode())):raise Failure(401,'UNAUTHORIZED','请导入有效的手机连接配置')
        parsed=urlsplit(target)
        if parsed.query or '%' in parsed.path or '..' in parsed.path:raise Failure(400,'INVALID_PATH','请求路径无效')
        parts=parsed.path.strip('/').split('/')
        realtime_phone = parts[:2] == ['v1','realtime']
        realtime_worker = parts[:3] == ['v1','worker','realtime']
        if realtime_phone or realtime_worker:
            action = parts[3:] if realtime_worker else parts[2:]
            if method == 'GET' and action in [[], ['state']]:
                return 200,self.realtime.public()
            if method == 'POST':
                try:
                    value=json.loads(body)
                    if not isinstance(value,dict):raise ValueError()
                    if realtime_phone and action==['settings']:
                        return 200,self.realtime.configure(value)
                    if realtime_phone and action==['scan'] and not value:return 202,self.realtime.request_scan()
                    if realtime_phone and action==['test'] and not value:return 202,self.realtime.test_notification()
                    if realtime_worker:
                        if action==['state'] and not value:return 200,self.realtime.public()
                        if action==['claim'] and not value:return 200,{'job':self.realtime.claim('mac')}
                        if action==['renew'] and set(value)=={'lease'}:
                            accepted=self.realtime.renew(value['lease'])
                        elif action==['publish'] and set(value)=={'lease','report'}:
                            accepted=self.realtime.publish(value['lease'],value['report'])
                        elif action==['failure'] and set(value)=={'lease'}:
                            accepted=self.realtime.fail(value['lease'])
                        else:raise ValueError()
                        if not accepted:raise Failure(409,'LEASE_EXPIRED','盘中执行连接已过期')
                        return 200,{'accepted':True}
                except BlockingIOError:raise Failure(429,'COOLDOWN','请稍后重试，每分钟最多一次')
                except (ValueError,TypeError,KeyError):raise Failure(400,'INVALID_BODY','盘中请求无效，请检查设置或数据时间')
            raise Failure(404,'NOT_FOUND','盘中接口不存在')
        if worker and method=='POST':
            try:value=json.loads(body)
            except (ValueError,UnicodeError):raise Failure(400,'INVALID_BODY','Invalid worker message')
            if not isinstance(value,dict):raise Failure(400,'INVALID_BODY','Invalid worker message')
            if parts==['v1','worker','heartbeat'] and set(value) in [set(),{'job_id','lease'}]:
                if value and (not canonical_uuid(value['job_id']) or not isinstance(value['lease'],str) or not re.fullmatch(r'[a-f0-9]{64}',value['lease'])):raise Failure(400,'INVALID_BODY','Invalid execution lease')
                if not self.queue.heartbeat(**value):raise Failure(409,'LEASE_EXPIRED','Execution lease expired')
                return 200,{'accepted':True}
            if parts==['v1','worker','claim'] and not value:
                self.queue.heartbeat();return 200,{'job':self.queue.claim('mac')}
            if parts==['v1','worker','failure'] and set(value)=={'job_id','lease'} and canonical_uuid(value['job_id']) and isinstance(value['lease'],str):
                if not self.queue.failed(value['job_id'],value['lease']):raise Failure(409,'LEASE_EXPIRED','Execution lease expired')
                return 200,{'accepted':True}
        if method=='GET' and parts==['v1','status']:
            info=self.queue.capabilities()
            online=time.time()-info.get('heartbeat',0)<30
            available={}
            for strategy in STRATEGIES:
                try:available[strategy]=current_manifest(self.root,strategy)
                except (OSError,ValueError,KeyError):pass
            return 200,dict(schema_version=1,job=self.state(),worker_online=online,mac_online=self.queue.mac_online(),
                can_refresh=online and info.get('can_refresh',False),reports=available)
        if method=='POST' and parts==['v1','jobs']:
            try:value=json.loads(body)
            except (ValueError,UnicodeError):raise Failure(400,'INVALID_BODY','任务参数无效')
            if not isinstance(value,dict) or set(value)!={'action','request_id'} or value['action'] not in ['refresh','recompute'] or not canonical_uuid(value['request_id']):
                raise Failure(400,'INVALID_BODY','任务参数无效')
            info=self.queue.capabilities()
            if time.time()-info.get('heartbeat',0)>=30:raise Failure(503,'WORKER_OFFLINE','计算服务暂时离线，已有结果仍可使用')
            if value['action']=='refresh' and not info.get('can_refresh'):raise Failure(409,'UPDATE_UNAVAILABLE','服务器尚未配置行情更新凭据')
            try:return 202,self.queue.submit(value['action'],value['request_id'])
            except BlockingIOError:raise Failure(429,'COOLDOWN','刚执行过任务，请稍后再试')
        if method=='GET' and len(parts)>=4 and parts[:2]==['v1','reports'] and parts[2] in STRATEGIES:
            strategy=parts[2]
            if len(parts)==4 and parts[3]=='current':return 200,current_manifest(self.root,strategy)
            if not GENERATION.fullmatch(parts[3]):raise Failure(400,'INVALID_VERSION','数据版本无效')
            release=self.root/'releases'/parts[3]
            if len(parts)==5 and parts[4]=='report.json':return 200,checked_file(self.root,release/strategy/'report.json',MAX_REPORT)
            if len(parts)==6 and parts[4]=='charts' and parts[5].endswith('.json') and CODE.fullmatch(parts[5][:-5]):
                return 200,checked_file(self.root,release/'charts'/parts[5],MAX_CHART)
        raise Failure(404,'NOT_FOUND','没有找到这个数据接口')


class Handler(BaseHTTPRequestHandler):
    server_version='Guanlan';sys_version=''
    def log_message(self,*args):pass  # Never log request headers, tokens, or paths.
    def do_GET(self):self.handle_api()
    def do_POST(self):self.handle_api()
    def do_PUT(self):self.handle_api()
    def handle_api(self):
        self.connection.settimeout(10)
        try:
            length=int(self.headers.get('Content-Length','0'))
            if self.headers.get('Transfer-Encoding'):raise Failure(400,'INVALID_BODY','不支持该传输格式')
            if self.command=='PUT':
                self.connection.settimeout(180)
                status,value=self.server.service.upload(self.path,self.headers.get('Authorization',''),self.headers.get('X-Guanlan-Lease',''),self.rfile,length)
            else:
                body_limit=256*1024 if self.path=='/v1/worker/realtime/publish' else (4096 if self.path in ['/v1/realtime/settings','/v1/worker/realtime/settings'] else 1024)
                if not 0<=length<=body_limit:raise Failure(413,'TOO_LARGE','请求体过大')
                body=self.rfile.read(length)
                status,value=self.server.service.dispatch(self.command,self.path,self.headers.get('Authorization',''),body)
            data=value.read_bytes() if isinstance(value,Path) else json.dumps(value,ensure_ascii=False,allow_nan=False).encode()
        except Failure as error:
            status=error.status;data=json.dumps({'error':{'code':error.code,'message':error.message}},ensure_ascii=False).encode()
        except (FileNotFoundError,ValueError,KeyError):
            status=404;data=b'{"error":{"code":"SNAPSHOT_UNAVAILABLE","message":"Snapshot unavailable; sync again"}}'
        except Exception:
            status=500;data=b'{"error":{"code":"SERVER_ERROR","message":"Service temporarily unavailable"}}'
        try:
            self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8')
            self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(data)
        except (BrokenPipeError,ConnectionResetError,TimeoutError):pass


class BoundedServer(ThreadingMixIn,HTTPServer):
    daemon_threads=True
    slots=threading.BoundedSemaphore(4)
    def process_request(self,request,address):
        if not self.slots.acquire(blocking=False):self.shutdown_request(request);return
        try:super().process_request(request,address)
        except BaseException:self.slots.release();raise
    def process_request_thread(self,request,address):
        try:super().process_request_thread(request,address)
        finally:self.slots.release()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--config',type=Path,required=True);args=parser.parse_args()
    config=json.loads(args.config.read_text())
    server=BoundedServer(('127.0.0.1',config.get('port',8787)),Handler)
    server.service=Service(Path(config['root']),config['token'],config.get('worker_token'));server.serve_forever()
