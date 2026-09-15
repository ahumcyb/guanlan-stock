"""Own the native client lifecycle; only start/login after a server grant."""
import argparse
import http.client
from urllib.error import HTTPError
import fcntl
import json
import os
import signal
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request,build_opener,ProxyHandler
from engine.datta import NoRedirect
from engine.datta_session import shared_clock
from .artifacts import atomic_json


def admin(action,values=None):
    request=Request('http://127.0.0.1:9527/api/'+action,
        data=None if values is None else urlencode(values).encode(),method='GET' if values is None else 'POST')
    with build_opener(ProxyHandler({}),NoRedirect()).open(request,timeout=5) as response:
        raw=response.read(65537)
    if len(raw)>65536:raise ValueError('Invalid local client reply')
    return json.loads(raw)


class NativeClient:
    def __init__(self,config):self.config=config;self.process=None

    def stop(self):
        # Process exit is the handoff acknowledgement; never release before it.
        if self.process is not None:
            try:os.killpg(self.process.pid,signal.SIGTERM)
            except ProcessLookupError:pass
            try:self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(self.process.pid,signal.SIGKILL);self.process.wait(timeout=5)
            self.process=None
        else:
            try:admin('exit',{})
            except OSError:pass
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            try:admin('status')
            except OSError:return
            time.sleep(.2)
        raise ValueError('Local client has not stopped')

    def start(self):
        self.process=subprocess.Popen([self.config['executable']],cwd=self.config['client_directory'],
            stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
        deadline=time.monotonic()+30
        while time.monotonic()<deadline:
            if self.process.poll() is not None:raise ValueError('Datta client exited')
            try:
                state=admin('status')
                if state.get('exeConnected'):break
            except OSError:pass
            time.sleep(.5)
        else:raise ValueError('Datta client did not start')
        if not state.get('isLoggedIn'):
            credentials=Path(self.config['credentials'])
            if credentials.stat().st_mode&0o077:raise ValueError('Credential permissions')
            saved=json.loads(credentials.read_text())
            admin('login',{'phone':saved['phone'],'password':saved['password']})
        deadline=time.monotonic()+20
        while time.monotonic()<deadline:
            state=admin('status')
            if state.get('isLoggedIn') and state.get('isVerified'):
                admin('autostart/off',{})
                if not state.get('running'):admin('server/start',{'port':8080})
                state=admin('status')
                if state.get('running') and not state.get('autostart'):return
            time.sleep(.5)
        raise ValueError('Datta session unavailable')


def transient_transport(error):
    status=getattr(error,'status',getattr(error,'code',None))
    if isinstance(status,int):return status==429 or 500<=status<=599
    return isinstance(error,(OSError,http.client.HTTPException))


def transport_grace(error,stage,valid_until,alive,now):
    return stage in ['poll','status','activate'] and alive and valid_until-now>10 and transient_transport(error)


def log_event(event,node,stage,epoch=None,error=None,client=None):
    value=dict(event=event,node=node,stage=stage,time=time.time(),epoch=epoch)
    if error is not None:
        value['error_type']=type(error).__name__
        status=getattr(error,'status',getattr(error,'code',None))
        if isinstance(status,int):value['http_status']=status
    if client is not None:
        value['client']={k:client.get(k) is True for k in ['exeConnected','isLoggedIn','isVerified','running']}
    try:print(json.dumps(value,separators=(',',':')),flush=True)
    except OSError:pass


def serve(config):
    node=config['node'];receipt=Path(config['receipt']);receipt.parent.mkdir(parents=True,exist_ok=True)
    fd=os.open(receipt.with_suffix('.lock'),os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    lock=os.fdopen(fd,'a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    if node=='mac':
        from .mac_worker import WorkerClient
        remote=WorkerClient(json.loads(Path(config['worker_config']).read_text()))
        def call(action,token=None):return remote.request('/v1/worker/datta/'+action,{} if token is None else {'token':token})
    else:
        from .datta_ownership import DattaLeaseStore
        store=DattaLeaseStore(Path(config['server_root']))
        def call(action,token=None):
            if action=='poll':return store.poll('server',token)
            return {'accepted':getattr(store,action)('server',token)}
    native=NativeClient(config);stop=threading.Event();token=None
    valid_until=0;restart_at=0;failures=0;epoch=None;shutdown_pending=False
    def invalidate():
        try:atomic_json(receipt,{'phase':'waiting','pid':os.getpid()})
        except OSError:
            # A broken/full filesystem must not prevent native process cleanup.
            try:receipt.unlink(missing_ok=True)
            except OSError:pass
            log_event('datta_receipt_unavailable',node,'receipt',epoch)
    def shutdown(*_):stop.set()
    signal.signal(signal.SIGTERM,shutdown);signal.signal(signal.SIGINT,shutdown)
    try:
        invalidate();native.stop()
        while not stop.is_set():
            stage='poll'
            try:
                if shutdown_pending:
                    stage='shutdown';native.stop();shutdown_pending=False
                stage='poll'
                before=shared_clock();grant=call('poll',token)
                if grant.get('token') is None or grant.get('phase')=='draining':
                    invalidate();valid_until=0
                    if token:
                        stage='shutdown';shutdown_pending=True;native.stop();shutdown_pending=False;call('release',token);token=None
                        log_event('datta_released',node,stage,epoch)
                else:
                    if token is None:token=grant['token']
                    epoch=grant['epoch']
                    if native.process is None:
                        if shared_clock()<restart_at:
                            stop.wait(5);continue
                        stage='start';native.start()
                        before=shared_clock();stage='poll';grant=call('poll',token)
                        if grant.get('token')!=token or grant.get('phase')=='draining':raise ValueError('Source ownership changed')
                    stage='status';state=admin('status')
                    if not all(state.get(k) for k in ['exeConnected','isLoggedIn','isVerified','running']):
                        log_event('datta_client_unready',node,stage,epoch,client=state)
                        raise ValueError('Datta session lost')
                    if shared_clock()-before>40:raise ValueError('Source renewal delayed')
                    stage='receipt';next_valid_until=before+45
                    atomic_json(receipt,dict(phase='active',clock='system_monotonic_v1',node=node,epoch=epoch,pid=os.getpid(),
                        boot_epoch=time.time()-shared_clock(),valid_until_monotonic=next_valid_until))
                    valid_until=next_valid_until
                    if grant['phase'] in ['reserved','recovering']:
                        stage='activate'
                        if not call('activate',token)['accepted']:raise ValueError('Source activation refused')
                        log_event('datta_active',node,stage,epoch)
                    failures=0
            except Exception as error:
                alive=native.process is not None and native.process.poll() is None
                if token and transport_grace(error,stage,valid_until,alive,shared_clock()):
                    # Keep the ORIGINAL bounded receipt; never extend a lease
                    # using a failed request. One brief outage must not discard
                    # a long computation whose data is already sealed.
                    log_event('datta_transport_retry',node,stage,epoch,error)
                    stop.wait(5);continue
                log_event('datta_recovering',node,stage,epoch,error)
                invalidate();valid_until=0;shutdown_pending=True
                if token:
                    try:call('deactivate',token)
                    except Exception:pass
                try:
                    native.stop();shutdown_pending=False
                except Exception as shutdown_error:
                    log_event('datta_shutdown_pending',node,'shutdown',epoch,shutdown_error)
                    stop.wait(5);continue
                failures+=1;restart_at=shared_clock()+min(300,5*2**min(failures,6))
                if token:
                    try:
                        grant=call('poll',token)
                        if grant.get('token')==token and grant.get('phase')!='draining':
                            # The same node still owns login. Repair the client
                            # without changing epoch or cancelling sealed work.
                            if not call('deactivate',token)['accepted']:raise ValueError('Source repair refused')
                            stop.wait(5);continue
                        call('release',token)
                    except Exception as control_error:
                        log_event('datta_control_retry',node,'poll',epoch,control_error)
                        stop.wait(5);continue
                token=None
            stop.wait(5)

    finally:
        invalidate()
        try:
            native.stop()
            if token:call('release',token)
        finally:lock.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--config',type=Path,required=True);args=parser.parse_args()
    if args.config.stat().st_mode&0o077:raise SystemExit('Supervisor configuration must have mode 600')
    serve(json.loads(args.config.read_text()))
