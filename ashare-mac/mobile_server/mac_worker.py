"""User LaunchAgent: Mac-first computation with renewable, fenced server leases."""
import argparse
import base64
import http.client
import json
import os
import re
import shutil
import signal
import ssl
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from .queue import canonical_uuid,closing_arguments


class LostLease(Exception):pass


class WorkerClient:
    def __init__(self,config):
        if config['endpoint']!='https://106.14.125.189' or not re.fullmatch('[a-f0-9]{64}',config['token']):raise ValueError('Invalid worker connection')
        certificate=base64.b64decode(config['certificate'],validate=True)
        if len(certificate)>16384:raise ValueError('Invalid worker certificate')
        self.context=ssl.create_default_context(cadata=ssl.DER_cert_to_PEM_cert(certificate))
        self.token=config['token']

    def request(self,path,value=None,upload=None,lease=None,method='POST'):
        connection=http.client.HTTPSConnection('106.14.125.189',context=self.context,timeout=180 if upload else 20)
        try:
            headers={'Authorization':'Bearer '+self.token,'Accept':'application/json'}
            if upload:
                headers.update({'X-Guanlan-Lease':lease,'Content-Length':str(upload.stat().st_size),'Content-Type':'application/zip'})
                with upload.open('rb') as body:connection.request('PUT',path,body=body,headers=headers)
            else:
                headers['Content-Type']='application/json';connection.request(method,path,None if method=='GET' else json.dumps(value or {}).encode(),headers)
            limit=2*1024*1024 if path.startswith(('/v1/worker/realtime/','/v1/realtime')) else (128*1024 if path.startswith('/v1/daily') else 65536)
            response=connection.getresponse();body=response.read(limit+1)
            if response.status==409:raise LostLease()
            if response.status not in (200,202) or len(body)>limit:raise ValueError('Worker request failed')
            return json.loads(body)
        finally:connection.close()


def run_job(client,config,job):
    if not canonical_uuid(job.get('id')) or not re.fullmatch('[a-f0-9]{64}',job.get('lease','')) or job.get('action') not in ['recompute','refresh']:raise ValueError('Invalid server job')
    root=Path(config['workspace']).resolve();root.mkdir(parents=True,exist_ok=True)
    work=root/str(uuid.uuid4());work.mkdir();stop=threading.Event();lost=threading.Event()
    claim={'job_id':job['id'],'lease':job['lease']}
    def renew():
        last_success=time.monotonic()
        while not stop.wait(15):
            try:client.request('/v1/worker/heartbeat',claim);last_success=time.monotonic()
            except LostLease:lost.set();return
            except Exception:
                if time.monotonic()-last_success>70:lost.set();return
    thread=threading.Thread(target=renew,daemon=True);thread.start()
    process=None
    def execute(arguments):
        nonlocal process
        process=subprocess.Popen([sys.executable,'-u','-m',*map(str,arguments)],start_new_session=True)
        deadline=time.monotonic()+1800
        while process.poll() is None:
            if lost.wait(.5) or time.monotonic()>deadline:raise LostLease()
        if process.returncode:raise ValueError('Computation failed')
        process=None
    try:
        print('Mac 已接管手机任务：'+job['action'],flush=True)
        execute(['engine.remote','--config',config['ssh_config'],'--cache',root/'market'])
        execute(['mobile_server.build','--data-root',root/'market/current','--overlay',root/'overlay','--work',work,'--action',job['action'],*closing_arguments(job)])
        if lost.is_set():raise LostLease()
        client.request('/v1/worker/uploads/'+job['id'],upload=work/'bundle.zip',lease=job['lease'])
        try:
            from engine.remote import cache_built_snapshot
            revision=json.loads((work/'packages/latest.json').read_text())['revision']
            cache_built_snapshot(work/'packages'/revision,root/'market')
        except (OSError,ValueError,KeyError):
            print('本机镜像预缓存未完成，已上传的服务器任务继续校验',flush=True)
        print('Mac 结果已上传，服务器正在校验发布',flush=True)
    except Exception:
        if not lost.is_set():
            try:client.request('/v1/worker/failure',claim)
            except Exception:pass
        raise
    finally:
        stop.set();thread.join(timeout=1)
        if process is not None and process.poll() is None:
            os.killpg(process.pid,signal.SIGTERM)
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.wait()
        shutil.rmtree(work,ignore_errors=True)


def main(config):
    client=WorkerClient(config)
    while True:
        try:
            client.request('/v1/worker/heartbeat')
            result=client.request('/v1/worker/claim')
            if result.get('job'):run_job(client,config,result['job'])
        except KeyboardInterrupt:return
        except LostLease:print('执行连接已失效，取消迟到计算，保留服务器现有结果',flush=True)
        except Exception:print('Mac 计算服务暂未完成连接或任务，稍后重试',flush=True)
        time.sleep(10)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True);a=p.parse_args()
    if a.config.stat().st_mode&0o077:raise SystemExit('Worker configuration must have mode 600')
    def stop(*_):raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM,stop)
    main(json.loads(a.config.read_text()))
