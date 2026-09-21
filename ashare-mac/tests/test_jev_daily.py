import json,tempfile,unittest
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from mobile_server.artifacts import STRATEGIES,atomic_json
from mobile_server.jev import digest,request_payload,decode
from mobile_server.jev_daily import load_input,process_daily,read_daily,request_daily
from mobile_server.realtime import RealtimeStore
from tests.test_jev import response
GEN='20260921T170000-abcdef';REV='20260921-'+'a'*16
NOW=datetime(2026,9,21,19,tzinfo=ZoneInfo('Asia/Shanghai')).timestamp()
OPEN=datetime(2026,9,22,9,30,tzinfo=ZoneInfo('Asia/Shanghai')).timestamp()
def fixture(root):
    folder=root/'releases'/GEN;folder.mkdir(parents=True);(root/'current').symlink_to('releases/'+GEN)
    for strategy in STRATEGIES:
        stock=dict(ts_code='000001.SZ',name='测试',trade_date='20260921',close=10.,change=2.,rank=1,state='入选',score=80.,industry='行业',stale=False,adjusted=True,limit_available=True,atr=.02,support=9.7,breakout=10.1,invalidation=9.4)
        report=dict(schema_version=1,strategy_id=strategy,strategy_name=strategy,as_of='20260921',data_revision=REV,generated_at='2026-09-21T17:00:00+08:00',stocks=[stock],shortlist_count=1,breadth=.6)
        if strategy=='orderflow':report['orderflow_status']={'status':'complete'}
        atomic_json(folder/strategy/'report.json',report);raw=(folder/strategy/'report.json').read_bytes()
        import hashlib
        atomic_json(folder/strategy/'manifest.json',dict(schema_version=1,generation=GEN,strategy=strategy,as_of='20260921',data_revision=REV,report_bytes=len(raw),report_sha256=hashlib.sha256(raw).hexdigest(),stock_count=1))
    return folder
class DailyJevTests(unittest.TestCase):
    def test_five_pools_merge_and_plan_lasts_only_until_next_market_open(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve();fixture(root)
            state=load_input(root,GEN,['20260921','20260922'])
            self.assertEqual(len(state['candidates']),1);self.assertEqual(len(state['candidates'][0]['strategies']),5)
            self.assertEqual(state['plan_expires_at'],OPEN)
            result=decode(response(request_payload(state)),state,NOW)
            self.assertFalse(result['historical']);self.assertEqual(result['rows'][0]['decision'],'buy')
            self.assertEqual(result['rows'][0]['scope'],'after_close')
            self.assertTrue(decode(response(request_payload(state)),state,OPEN)['historical'])
    def test_tampered_report_and_cross_version_are_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve();folder=fixture(root)
            p=folder/'leaders/report.json';p.write_bytes(p.read_bytes()+b' ')
            with self.assertRaises(ValueError):load_input(root,GEN,['20260921','20260922'])
    def test_worker_does_not_change_pools_and_is_deduplicated(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve();folder=fixture(root);before=(folder/'leaders/report.json').read_bytes()
            store=RealtimeStore(root,lambda:NOW);store.calendar(['20260921','20260922']);store.configure({'jev_enabled':True,'jev_key':'apikey_'+('a'*50)})
            calls=[]
            def transport(k,p):calls.append(p);return response(p)
            process_daily(store,transport);process_daily(store,transport)
            r=read_daily(store,GEN);self.assertEqual(r['status'],'ready');self.assertEqual(len(calls),1)
            self.assertEqual((folder/'leaders/report.json').read_bytes(),before)
            self.assertEqual(r['generation'],GEN);self.assertEqual(r['data_revision'],REV)
    def test_missing_calendar_never_creates_an_unbounded_entry_plan(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve();fixture(root)
            with self.assertRaises(ValueError):load_input(root,GEN,['20260921'])
    def test_old_generation_not_automatically_submitted_after_open(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve();fixture(root);store=RealtimeStore(root,lambda:OPEN+1);store.calendar(['20260921','20260922'])
            store.configure({'jev_enabled':True,'jev_key':'apikey_'+('a'*50)});calls=[]
            process_daily(store,lambda k,p:calls.append(p));self.assertFalse(calls)

    def test_api_requires_auth_and_retry_is_rate_limited(self):
        from mobile_server.api import Service,Failure
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve();fixture(root);service=Service(root,'a'*64);auth='Bearer '+'a'*64
            service.realtime.configure({'jev_enabled':True,'jev_key':'apikey_'+('a'*50)})
            url='/v1/jev/daily/'+GEN
            with self.assertRaises(Failure) as error:service.dispatch('GET',url,'')
            self.assertEqual(error.exception.status,401)
            self.assertEqual(service.dispatch('GET',url,auth)[1]['generation'],GEN)
            self.assertEqual(service.dispatch('POST',url,auth,b'{}')[0],202)
            with self.assertRaises(Failure) as error:service.dispatch('POST',url,auth,b'{}')
            self.assertEqual(error.exception.status,429)
    def test_disable_cancels_pending_and_key_rotation_does_not_revive_it(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve();fixture(root);store=RealtimeStore(root,lambda:NOW);store.calendar(['20260921','20260922'])
            store.configure({'jev_enabled':True,'jev_key':'apikey_'+('a'*50)})
            request_daily(store,GEN);store.configure({'jev_enabled':False})
            self.assertEqual(read_daily(store,GEN)['status'],'cancelled')
            store.configure({'jev_enabled':True,'jev_key':'apikey_'+('b'*50)})
            calls=[];process_daily(store,lambda k,p:calls.append(p));self.assertFalse(calls)
            self.assertEqual(read_daily(store,GEN)['status'],'cancelled')
    def test_interrupted_running_is_not_automatically_billed_again(self):
        from mobile_server.jev import save
        from mobile_server.jev_daily import result_path
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve();fixture(root);clock=[NOW];store=RealtimeStore(root,lambda:clock[0]);store.calendar(['20260921','20260922'])
            store.configure({'jev_enabled':True,'jev_key':'apikey_'+('a'*50)});request_daily(store,GEN)
            r=read_daily(store,GEN);r.update(status='running',started_at=NOW);save(result_path(store,GEN),r)
            clock[0]+=61;calls=[];process_daily(store,lambda k,p:calls.append(p))
            self.assertFalse(calls);self.assertEqual(read_daily(store,GEN)['status'],'unavailable')

    def test_unbilled_input_failure_retries_after_calendar_recovers(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve();fixture(root);clock=[NOW];store=RealtimeStore(root,lambda:clock[0]);store.calendar(['20260921'])
            store.configure({'jev_enabled':True,'jev_key':'apikey_'+('a'*50)});calls=[]
            def transport(k,p):calls.append(p);return response(p)
            process_daily(store,transport);self.assertEqual(read_daily(store,GEN)['status'],'waiting_input')
            store.calendar(['20260921','20260922']);process_daily(store,transport);self.assertFalse(calls)
            clock[0]+=61;process_daily(store,transport);self.assertEqual(len(calls),1)
            self.assertEqual(read_daily(store,GEN)['status'],'ready')
