"""Own the native client lifecycle; only start/login after a server grant."""
import argparse
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
    def invalidate():atomic_json(receipt,{'phase':'waiting','pid':os.getpid()})
    def shutdown(*_):stop.set()
    signal.signal(signal.SIGTERM,shutdown);signal.signal(signal.SIGINT,shutdown)
    try:
        invalidate();native.stop()
        while not stop.is_set():
            try:
                before=shared_clock();grant=call('poll',token)
                if grant.get('token') is None or grant.get('phase')=='draining':
                    invalidate()
                    if token:
                        native.stop();call('release',token);token=None
                else:
                    activating=token is None
                    if activating:
                        token=grant['token'];native.start()
                        # Login may take seconds. Revalidate before exposing it.
                        before=shared_clock()
                        grant=call('poll',token)
                        if grant.get('token')!=token or grant.get('phase')=='draining':raise ValueError('Source ownership changed')
                    state=admin('status')
                    if not all(state.get(k) for k in ['exeConnected','isLoggedIn','isVerified','running']):
                        raise ValueError('Datta session lost')
                    # A short local receipt expires well before the 90s remote
                    # lease, including a delayed/failed network response.
                    if shared_clock()-before>40:raise ValueError('Source renewal delayed')
                    atomic_json(receipt,dict(phase='active',clock='system_monotonic_v1',node=node,epoch=grant['epoch'],pid=os.getpid(),
                        boot_epoch=time.time()-shared_clock(),valid_until_monotonic=before+45))
                    if activating and not call('activate',token)['accepted']:raise ValueError('Source activation refused')
            except Exception:
                invalidate()
                try:native.stop()
                except Exception:
                    # Without confirmed shutdown do not acknowledge handoff.
                    print('达塔客户端尚未确认退出，保留交接等待',flush=True);stop.wait(5);continue
                if token:
                    try:call('release',token)
                    except Exception:pass
                token=None
                print('达塔登录权或客户端暂不可用，等待协调后重试',flush=True)
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
