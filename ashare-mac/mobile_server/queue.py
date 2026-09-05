"""Single job with renewable, fenced leases; Mac has priority over server fallback."""
import fcntl
import hmac
import json
import math
import os
import secrets
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from .artifacts import atomic_json,checked_file

ACTIVE={'queued','running','publishing'}
PUBLIC_FIELDS={'id','status','message','action','created_at','executor'}
FIELDS=PUBLIC_FIELDS|{'request_id','lease','lease_until','artifact_sha256','artifact_bytes'}


def canonical_uuid(value):
    try:return isinstance(value,str) and str(uuid.UUID(value))==value
    except (ValueError,AttributeError):return False


def number(value):return type(value) in (int,float) and math.isfinite(value) and value>=0


class JobQueue:
    def __init__(self,root,clock=time.time):
        self.root=root.resolve();self.root.mkdir(parents=True,exist_ok=True);self.clock=clock

    def read(self,name,default):
        path=self.root/name
        if not path.exists() and not path.is_symlink():return default
        value=json.loads(checked_file(self.root,path,65536).read_text())
        if not isinstance(value,dict):raise ValueError('Invalid worker state')
        return value

    def state(self):
        value=self.read('status.json',{'status':'idle','message':'准备就绪'})
        if (set(value)-FIELDS or value.get('status') not in ACTIVE|{'idle','completed','failed'}
                or not isinstance(value.get('message'),str) or len(value['message'])>200):raise ValueError('Invalid job state')
        for key in ['id','request_id']:
            if key in value and not canonical_uuid(value[key]):raise ValueError('Invalid job id')
        for key in ['created_at','lease_until']:
            if key in value and not number(value[key]):raise ValueError('Invalid job timestamp')
        if 'executor' in value and value['executor'] not in ['mac','server']:raise ValueError('Invalid executor')
        if 'action' in value and value['action'] not in ['recompute','refresh']:raise ValueError('Invalid action')
        for key in ['lease','artifact_sha256']:
            if key in value and (not isinstance(value[key],str) or len(value[key])!=64 or any(c not in '0123456789abcdef' for c in value[key])):raise ValueError('Invalid lease')
        if 'artifact_bytes' in value and (type(value['artifact_bytes']) is not int or not 0<value['artifact_bytes']<=256*1024*1024):raise ValueError('Invalid artifact size')
        if value['status']!='idle' and not {'id','request_id','created_at','action'}.issubset(value):raise ValueError('Incomplete job state')
        if value['status'] in ['running','publishing'] and not {'lease','lease_until','executor'}.issubset(value):raise ValueError('Incomplete lease')
        return value

    def public(self):return {k:v for k,v in self.state().items() if k in PUBLIC_FIELDS}

    def capabilities(self):
        value=self.read('capabilities.json',{})
        if set(value)-{'heartbeat','can_refresh'} or ('heartbeat' in value and not number(value['heartbeat'])) or ('can_refresh' in value and type(value['can_refresh']) is not bool):raise ValueError('Invalid worker capability')
        return value

    def mac_online(self):
        value=self.read('mac.json',{})
        if set(value)-{'heartbeat'} or ('heartbeat' in value and not number(value['heartbeat'])):raise ValueError('Invalid Mac heartbeat')
        return 0<=self.clock()-value.get('heartbeat',0)<45

    @contextmanager
    def locked(self):
        descriptor=os.open(self.root/'.queue.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o660)
        with os.fdopen(descriptor,'a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX);yield

    def save(self,state):atomic_json(self.root/'status.json',state)

    def expire(self,state):
        if state['status'] in ['running','publishing'] and state['lease_until']<=self.clock():
            state={k:v for k,v in state.items() if k in {'id','request_id','action','created_at'}}
            state.update(status='queued',message='执行连接中断，等待重新接管');self.save(state)
        return state

    def submit(self,action,request_id):
        if action not in ['refresh','recompute'] or not canonical_uuid(request_id):raise ValueError('Invalid job request')
        with self.locked():
            state=self.expire(self.state())
            if state.get('request_id')==request_id or state['status'] in ACTIVE:return self.public()
            if self.clock()-state.get('created_at',0)<(300 if action=='refresh' else 60):raise BlockingIOError('Cooldown')
            state=dict(id=str(uuid.uuid4()),request_id=request_id,action=action,status='queued',created_at=self.clock(),message='已提交，优先等待 Mac 计算')
            self.save(state);return self.public()

    def claim(self,executor):
        if executor not in ['mac','server']:raise ValueError('Invalid executor')
        with self.locked():
            state=self.expire(self.state())
            if state['status']!='queued' or (executor=='server' and self.mac_online()):return None
            state.update(status='running',executor=executor,lease=secrets.token_hex(32),lease_until=self.clock()+90,
                message='Mac 正在计算' if executor=='mac' else 'Mac 暂时离线，服务器正在计算')
            self.save(state);return state

    def owns(self,state,job_id,lease):
        return state['status'] in ['running','publishing'] and state.get('id')==job_id and isinstance(lease,str) and hmac.compare_digest(state.get('lease',''),lease) and state['lease_until']>self.clock()

    def heartbeat(self,job_id=None,lease=None,executor='mac'):
        with self.locked():
            if executor=='mac':atomic_json(self.root/'mac.json',{'heartbeat':self.clock()})
            if job_id is None:return True
            state=self.state()
            if state['status']!='running' or not self.owns(state,job_id,lease) or state['executor']!=executor:return False
            state['lease_until']=self.clock()+90;self.save(state);return True

    def progress(self,job_id,lease,message):
        with self.locked():
            state=self.state()
            if state['status']!='running' or not self.owns(state,job_id,lease):return False
            state['message']=str(message)[:200];self.save(state);return True

    def uploaded(self,job_id,lease,digest,size,source=None,destination=None):
        with self.locked():
            state=self.state()
            if state['status']!='running' or not self.owns(state,job_id,lease):return False
            if source is not None:
                if destination.exists() or destination.is_symlink():raise ValueError('Upload destination already exists')
                os.rename(source,destination)
            # Ownership transfers to the server publisher. Client endpoints cannot
            # renew, replace or cancel it. 30 minutes bounds even slow validation.
            state.update(status='publishing',lease_until=self.clock()+1800,artifact_sha256=digest,artifact_bytes=size,message='计算完成，正在校验并发布结果')
            self.save(state);return True

    def failed(self,job_id,lease):
        with self.locked():
            state=self.state()
            if state['status']!='running' or not self.owns(state,job_id,lease):return False
            state={k:v for k,v in state.items() if k in {'id','request_id','action','created_at','executor'}}
            state.update(status='failed',message='Mac 未完成本次计算，旧结果已保留；请检查本机运行记录后重试')
            self.save(state);return True
