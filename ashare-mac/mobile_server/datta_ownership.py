"""One persistent login owner shared by both computation queues (stdlib only)."""
import fcntl
import hmac
import json
import os
import secrets
import time
from functools import wraps
from contextlib import contextmanager
from pathlib import Path


class DattaLeaseStore:
    def __init__(self,root,clock=time.time):
        self.root=Path(root).resolve();self.jobs=self.root/'jobs'
        self.jobs.mkdir(parents=True,exist_ok=True);self.clock=clock
        with self.lock():
            if not self.path.exists():
                self.save(dict(epoch=0,owner=None,phase='idle',lease_until=0,mac_seen=self.clock()))

    @property
    def path(self):return self.jobs/'datta-owner.json'

    @contextmanager
    def lock(self):
        fd=os.open(self.jobs/'.datta-owner.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o660)
        with os.fdopen(fd,'a') as file:
            fcntl.flock(file,fcntl.LOCK_EX);yield

    def read(self):
        if self.path.is_symlink() or self.path.stat().st_size>4096:raise ValueError('Invalid Datta state')
        value=json.loads(self.path.read_text())
        if (value.get('owner') not in [None,'mac','server'] or value.get('phase') not in ['idle','reserved','active','draining']
                or type(value.get('epoch')) is not int):raise ValueError('Invalid Datta state')
        return value

    def save(self,value):
        from .realtime import durable_json
        durable_json(self.path,value)

    def matches(self,value,node,token):
        return (value['owner']==node and isinstance(token,str) and len(token)==64
            and hmac.compare_digest(value.get('token',''),token) and value['lease_until']>self.clock())

    def busy(self,node):
        # Called with the global lock. Claims take this same lock before their
        # individual queue lock, so no new task can appear during handoff.
        path=self.jobs/'status.json'
        if path.exists():
            v=json.loads(path.read_text())
            if v.get('executor')==node and v.get('status') in ['running','publishing'] and v.get('lease_until',0)>self.clock():return True
        path=self.jobs/'realtime/state.json'
        if path.exists():
            lease=json.loads(path.read_text()).get('lease') or {}
            if lease.get('executor')==node and lease.get('expires_at',0)>self.clock():return True
        return False

    def poll(self,node,token=None):
        if node not in ['mac','server']:raise ValueError('Invalid Datta node')
        with self.lock():
            v=self.read();now=self.clock()
            if node=='mac':v['mac_seen']=now
            if self.matches(v,node,token):
                if node=='server' and now-v['mac_seen']<120 and not self.busy(node):v['phase']='draining'
                v['lease_until']=now+90;self.save(v);return dict(v)
            if v['lease_until']>now:
                self.save(v);return dict(owner=v['owner'],phase='waiting')
            if v['owner'] and v['owner']!=node and self.busy(v['owner']):
                self.save(v);return dict(owner=v['owner'],phase='waiting')
            # An expired process cannot revive its old token. It must clean up
            # and explicitly request a new epoch without a token.
            if token is not None:
                self.save(v);return dict(owner=v['owner'],phase='waiting')
            if node=='server' and now-v['mac_seen']<120:
                self.save(v);return dict(owner=v['owner'],phase='waiting')
            v.update(owner=node,phase='reserved',epoch=v['epoch']+1,token=secrets.token_hex(32),lease_until=now+90)
            self.save(v);return dict(v)

    def activate(self,node,token):
        with self.lock():
            v=self.read()
            if not self.matches(v,node,token) or v['phase'] not in ['reserved','active']:return False
            v['phase']='active';self.save(v);return True

    def release(self,node,token):
        with self.lock():
            v=self.read()
            if not self.matches(v,node,token):return False
            v.update(owner=None,phase='idle',lease_until=0);v.pop('token',None);self.save(v);return True

    def allowed(self,node):
        v=self.read()
        return v['owner']==node and v['phase']=='active' and v['lease_until']>self.clock()

    def public(self):
        with self.lock():
            v=self.read()
            return {k:v[k] for k in ['owner','phase','epoch','lease_until']}


@contextmanager
def claim_gate(root,node,clock=time.time):
    """Legacy fixtures have no broker state; deployed nodes create it first."""
    if not (Path(root)/'jobs/datta-owner.json').exists():
        yield True;return
    store=DattaLeaseStore(root,clock)
    with store.lock():
        value=store.read()
        # Mac returning prevents Linux from starting another task; current work
        # can still renew, finish and publish before its client is shut down.
        allowed=store.allowed(node) and not (node=='server' and clock()-value['mac_seen']<120)
        yield value if allowed else None


def epoch_valid(root,node,epoch,now):
    if epoch is None:return not (Path(root)/'jobs/datta-owner.json').exists()
    try:
        value=json.loads((Path(root)/'jobs/datta-owner.json').read_text())
        return value['epoch']==epoch and value['owner']==node and value['phase']=='active' and value['lease_until']>now
    except (OSError,ValueError,KeyError,TypeError):return False


def job_environment(job):
    value=dict(os.environ);value.pop('GUANLAN_DATTA_EPOCH',None)
    if 'datta_epoch' in job:
        epoch=job['datta_epoch']
        if type(epoch) is not int or epoch<1:raise ValueError('Invalid source epoch')
        value['GUANLAN_DATTA_EPOCH']=str(epoch)
    return value


def serialize_source(parent_levels):
    """Atomically fence task mutations, always global lock before queue lock."""
    def decorate(method):
        @wraps(method)
        def invoke(self,*args,**kwargs):
            root=self.root
            for _ in range(parent_levels):root=root.parent
            if not (root/'jobs/datta-owner.json').exists():return method(self,*args,**kwargs)
            store=DattaLeaseStore(root,self.clock)
            with store.lock():return method(self,*args,**kwargs)
        return invoke
    return decorate
