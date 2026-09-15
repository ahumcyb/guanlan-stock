from .datta_ownership import job_environment
"""Server coordinator: publish Mac results, compute only when Mac is unreachable."""
import argparse
import json
import os
import selectors
import shutil
import signal
import subprocess
import sys
import time
import uuid
import threading
import traceback
from pathlib import Path
from engine.snapshot_protocol import sha256_file
from .artifacts import atomic_json
from .queue import JobQueue,PERSISTENT_FIELDS,closing_arguments
from .ingest import activate


def fail(queue,job,message):
    from .datta_ownership import DattaLeaseStore
    store=DattaLeaseStore(queue.root.parent,queue.clock)
    with store.lock():
        with queue.locked():
            state=queue.state()
            if queue.owns(state,job['id'],job['lease']):
                state={k:v for k,v in state.items() if k in PERSISTENT_FIELDS|{'executor'}}
                state.update(status='failed',message=message);queue.save(state)

def serve(root,market):
    queue=JobQueue(root/'jobs');started=time.monotonic();process=None;job=None;work=None;selector=None;buffer=b''
    last_renew=0;deadline=0
    stopped=threading.Event()
    def heartbeat():
        while not stopped.is_set():
            from .datta_ownership import DattaLeaseStore
            source=DattaLeaseStore(root).public()
            ready=source['phase']=='active' and source['lease_until']>time.time()
            atomic_json(root/'jobs/capabilities.json',{'heartbeat':time.time(),'can_refresh':ready})
            stopped.wait(5)
    pulse=threading.Thread(target=heartbeat,daemon=True);pulse.start()
    try:
        while True:
            if process is not None:
                if time.monotonic()-last_renew>15:
                    queue.heartbeat(job['id'],job['lease'],executor='server');last_renew=time.monotonic()
                for key,_ in selector.select(timeout=.1):
                    data=os.read(key.fd,4096)
                    if data:
                        buffer=(buffer+data)[-16384:]
                        if b'\n' in buffer:
                            lines=buffer.split(b'\n');buffer=lines[-1]
                            queue.progress(job['id'],job['lease'],'服务器计算中 · '+lines[-2].decode('utf-8',errors='replace')[:150])
                if time.monotonic()>deadline or not queue.owns(queue.state(),job['id'],job['lease']):
                    os.killpg(process.pid,signal.SIGTERM)
                    try:process.wait(timeout=5)
                    except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.wait()
                    fail(queue,job,'备用计算超时或失去执行权限，旧结果已保留')
                if process.poll() is not None:
                    selector.close();process.stdout.close()
                    if process.returncode==0 and queue.owns(queue.state(),job['id'],job['lease']):
                        bundle=work/'bundle.zip';destination=root/'incoming'/(job['id']+'-'+job['lease']+'.zip')
                        queue.uploaded(job['id'],job['lease'],sha256_file(bundle),bundle.stat().st_size,bundle,destination)
                    elif process.returncode!=0:fail(queue,job,'备用计算未完成，旧结果已保留')
                    shutil.rmtree(work,ignore_errors=True);process=None
            state=queue.state()
            if state['status']=='publishing' and queue.owns(state,state['id'],state['lease']):
                bundle=root/'incoming'/(state['id']+'-'+state['lease']+'.zip')
                try:
                    activate(bundle,root,market,queue,state)
                    print('已校验并发布 '+state['executor']+' 的计算结果',flush=True)
                except Exception as error:
                    # Frames and errno identify failures without logging tokens, upload paths or payloads.
                    frames=' > '.join(f'{frame.name}:{frame.lineno}' for frame in traceback.extract_tb(error.__traceback__))
                    print(f'Publication failed: {type(error).__name__} errno={getattr(error,"errno",None)} at {frames}',flush=True)
                    fail(queue,state,'结果校验或发布未完成，旧报告已保留，请重新计算')
                finally:
                    if bundle.exists():bundle.unlink()
            if process is None and time.monotonic()-started>=60:
                job=queue.claim('server')
                if job:
                    work=root/'work'/str(uuid.uuid4());work.mkdir(mode=0o700)
                    process=subprocess.Popen([sys.executable,'-u','-m','mobile_server.build','--data-root',str(market/'current'),
                        '--overlay',str(root/'overlay'),'--work',str(work),'--action',job['action'],*closing_arguments(job)],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,start_new_session=True,env=job_environment(job))
                    os.set_blocking(process.stdout.fileno(),False);selector=selectors.DefaultSelector();selector.register(process.stdout,selectors.EVENT_READ)
                    deadline=time.monotonic()+1800;last_renew=time.monotonic();buffer=b''
                    print('Mac 离线，服务器接管任务',flush=True)
            time.sleep(2)
    finally:
        stopped.set();pulse.join(timeout=1)
        if process is not None and process.poll() is None:
            os.killpg(process.pid,signal.SIGTERM)
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.wait()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--market-root',type=Path,required=True);a=p.parse_args()
    signal.signal(signal.SIGTERM,lambda *_:sys.exit(0))
    serve(a.root.resolve(),a.market_root.resolve())
