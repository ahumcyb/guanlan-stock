import copy
import tempfile
import unittest
from pathlib import Path
from mobile_server.jev import make_input,decode,request_payload,attach,process_one,request_review
from mobile_server.realtime import RealtimeStore
NOW=1789966800.
def report():
    row=dict(ts_code='000001.SZ',name='测试',price=10.,change=4.,quote_at=NOW-15,reference_date='20260918',
        strategy='overnight',checks=['上涨4%','均线多头'],pending=['公告未核查'],volume_multiple=1.8,volume_ratio=2.,vwap=9.9,state='规则通过')
    return dict(slot='20260921-1430',date='20260921',previous_date='20260918',generated_at=NOW,kind='screen',status='ready',executor='mac',
        strategies={'overnight':[row],'golden':[]},reviews=[],warnings=[],message='完成',orderflow=dict(status='ready',candidates=[dict(row,strategy='orderflow')]))
def response(payload,choice='buy',confidence=.9):
    answers={}
    for key,q in payload['questions'].items():
        value=choice if key.endswith('_decision') else 'trend_volume'
        answers[key]=dict(type='choice',choice=value,confidence=confidence,probabilities={k:1. if k==value else 0. for k in q['criteria']})
    return dict(model='jev-1.13.0',answers=answers,usage={'input_tokens':100,'output_tokens':20})
class JevTests(unittest.TestCase):
    def test_union_four_strategies_dedup_and_no_private_fields(self):
        r=report();r['token']='never-send';state=make_input(r)
        self.assertEqual(len(state['candidates']),1);self.assertEqual(len(state['candidates'][0]['strategies']),2)
        self.assertNotIn('token',str(state));self.assertNotIn('never-send',str(state))
        r['status']='blocked';self.assertEqual(make_input(r)['candidates'][0]['strategies'],['orderflow'])
    def test_choice_validation_and_low_confidence_cannot_be_buy(self):
        state=make_input(report());p=request_payload(state)
        result=decode(response(p),state,NOW);self.assertEqual(result['rows'][0]['decision'],'buy')
        low=decode(response(p,confidence=.4),state,NOW);self.assertEqual(low['rows'][0]['decision'],'watch')
        invalid=response(p);invalid['answers']['c0_decision']['probabilities']['buy']=.5
        with self.assertRaises(ValueError):decode(invalid,state,NOW)
        invalid=response(p);invalid['answers']['extra']={}
        with self.assertRaises(ValueError):decode(invalid,state,NOW)
    def test_expired_results_are_historical_not_current_buy_calls(self):
        state=make_input(report());p=request_payload(state);r=decode(response(p),state,NOW+200)
        self.assertTrue(r['historical']);self.assertEqual(r['rows'][0]['decision'],'watch');self.assertEqual(r['rows'][0]['model_choice'],'buy')
    def test_sidecar_binding_and_archive_is_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            store=RealtimeStore(Path(d),lambda:NOW);r=report();store.save(dict(runs=[r],events=[],done=[]))
            archive=store.root/'run-archive'/(r['slot']+'.json');before=archive.read_bytes()
            store.configure({'jev_key':'apikey_'+('a'*50),'jev_enabled':True})
            request_review(store,r['slot']);process_one(store,lambda key,p:response(p))
            value=attach(store.root,r);self.assertEqual(value['strategies']['overnight'][0]['jev']['decision'],'buy')
            self.assertEqual(archive.read_bytes(),before)
            wrong=copy.deepcopy(r);wrong['strategies']['overnight'][0]['price']=11
            self.assertNotIn('jev',attach(store.root,wrong))
            public=store.public_settings();self.assertTrue(public['jev_configured']);self.assertNotIn('jev_key',public)
    def test_duplicate_process_and_disabled_key_do_not_call_provider(self):
        with tempfile.TemporaryDirectory() as d:
            store=RealtimeStore(Path(d),lambda:NOW);store.save(dict(runs=[report()],events=[],done=[]))
            store.configure({'jev_key':'apikey_'+('a'*50),'jev_enabled':True});calls=[]
            def transport(key,p):calls.append(p);return response(p)
            process_one(store,transport);process_one(store,transport);self.assertEqual(len(calls),1)
            store.configure({'clear_jev':True});self.assertFalse(store.public_settings()['jev_configured'])

class JevBoundaryTests(unittest.TestCase):
    def test_inconsistent_choice_and_reason_cannot_give_conflicting_advice(self):
        state=make_input(report());p=request_payload(state)
        r=decode(response(p,choice='avoid'),state,NOW)['rows'][0]
        self.assertEqual(r['decision'],'watch');self.assertIn('不一致',r['explanation'])
    def test_expired_notification_is_not_dispatched_with_a_new_ttl(self):
        with tempfile.TemporaryDirectory() as d:
            clock=[NOW+160];store=RealtimeStore(Path(d),lambda:clock[0]);store.save(dict(runs=[report()],events=[],done=[]))
            store.configure({'jev_key':'apikey_'+('a'*50),'jev_enabled':True,'bark_url':'https://api.day.app/testDeviceKeyForJev123456'})
            process_one(store,lambda k,p:response(p))
            self.assertEqual(store.state()['events'][0]['expires_at'],NOW+165)
            clock[0]=NOW+200;self.assertIsNone(store.take_event());self.assertEqual(store.state()['events'][0]['status'],'expired')
    def test_settings_changed_before_dispatch_cancel_without_calling(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as d:
            store=RealtimeStore(Path(d),lambda:NOW);store.save(dict(runs=[report()],events=[],done=[]))
            store.configure({'jev_key':'apikey_'+('a'*50),'jev_enabled':True})
            original=store.settings;reads=[];calls=[]
            def settings():
                value=original();reads.append(1)
                if len(reads)>=2:value=dict(value,jev_enabled=False)
                return value
            with patch.object(store,'settings',side_effect=settings):process_one(store,lambda k,p:calls.append(p))
            self.assertFalse(calls)
    def test_inflight_response_cannot_overwrite_a_new_requested_generation(self):
        from mobile_server.jev import sidecar,save
        with tempfile.TemporaryDirectory() as d:
            store=RealtimeStore(Path(d),lambda:NOW);store.save(dict(runs=[report()],events=[],done=[]));store.configure({'jev_key':'apikey_'+('a'*50),'jev_enabled':True})
            def transport(key,p):
                path=sidecar(store.root,report()['slot']);import json
                value=json.loads(path.read_text());value.update(request_id='new-request',status='pending');save(path,value);return response(p)
            process_one(store,transport)
            import json
            value=json.loads(sidecar(store.root,report()['slot']).read_text());self.assertEqual(value['request_id'],'new-request');self.assertEqual(value['status'],'pending')

class JevRecoveryTests(unittest.TestCase):
    def test_missing_queue_sidecar_does_not_block_following_work(self):
        from mobile_server.jev import save
        with tempfile.TemporaryDirectory() as d:
            store=RealtimeStore(Path(d),lambda:NOW);store.save(dict(runs=[report()],events=[],done=[]));store.configure({'jev_key':'apikey_'+('a'*50),'jev_enabled':True})
            save(store.root/'jev-queue.json',['20260918-1430'])
            process_one(store,lambda k,p:response(p))
            self.assertEqual(attach(store.root,report())['jev']['status'],'ready')
    def test_orphan_pending_request_is_recovered_without_queue(self):
        with tempfile.TemporaryDirectory() as d:
            store=RealtimeStore(Path(d),lambda:NOW);store.save(dict(runs=[report()],events=[],done=[]));store.configure({'jev_key':'apikey_'+('a'*50),'jev_enabled':True})
            request_review(store,report()['slot']);(store.root/'jev-queue.json').unlink()
            process_one(store,lambda k,p:response(p));self.assertEqual(attach(store.root,report())['jev']['status'],'ready')
    def test_clear_finishes_before_dispatch_so_old_key_is_not_sent(self):
        import threading
        from unittest.mock import patch
        from mobile_server import jev
        with tempfile.TemporaryDirectory() as d:
            store=RealtimeStore(Path(d),lambda:NOW);store.save(dict(runs=[report()],events=[],done=[]));store.configure({'jev_key':'apikey_'+('a'*50),'jev_enabled':True})
            entered=threading.Event();resume=threading.Event();calls=[];original=jev.request_payload
            def paused(state):entered.set();self.assertTrue(resume.wait(3));return original(state)
            with patch.object(jev,'request_payload',side_effect=paused):
                worker=threading.Thread(target=process_one,args=(store,lambda k,p:calls.append(p)));worker.start()
                self.assertTrue(entered.wait(3));store.configure({'clear_jev':True});resume.set();worker.join(3)
            self.assertFalse(worker.is_alive());self.assertFalse(calls)

class JevNotificationBindingTests(unittest.TestCase):
    def test_later_manual_judgment_does_not_replace_the_notified_attempt(self):
        with tempfile.TemporaryDirectory() as d:
            clock=[NOW];store=RealtimeStore(Path(d),lambda:clock[0]);store.save(dict(runs=[report()],events=[],done=[]));store.configure({'jev_key':'apikey_'+('a'*50),'jev_enabled':True})
            process_one(store,lambda k,p:response(p));event=store.state()['events'][0]
            self.assertEqual(store.event_detail(event['id'])['report']['jev']['rows'][0]['model_choice'],'buy')
            clock[0]+=61;request_review(store,report()['slot'])
            process_one(store,lambda k,p:response(p,choice='watch'))
            self.assertEqual(attach(store.root,report())['jev']['rows'][0]['model_choice'],'watch')
            self.assertEqual(store.event_detail(event['id'])['report']['jev']['rows'][0]['model_choice'],'buy')

class JevGenerationTests(unittest.TestCase):
    def test_clear_orphan_then_new_key_never_revives_old_paid_request(self):
        with tempfile.TemporaryDirectory() as d:
            store=RealtimeStore(Path(d),lambda:NOW);store.save(dict(runs=[report()],events=[],done=[]));store.configure({'jev_key':'apikey_'+('a'*50),'jev_enabled':True})
            request_review(store,report()['slot']);(store.root/'jev-queue.json').unlink()
            store.configure({'clear_jev':True});store.configure({'jev_key':'apikey_'+('b'*50),'jev_enabled':True})
            calls=[];process_one(store,lambda k,p:calls.append(p))
            self.assertFalse(calls);self.assertEqual(attach(store.root,report())['jev']['status'],'cancelled')

class JevIntegrityTests(unittest.TestCase):
    def test_changed_stored_judgment_is_not_attached(self):
        import json
        from mobile_server.jev import sidecar
        with tempfile.TemporaryDirectory() as d:
            store=RealtimeStore(Path(d),lambda:NOW);store.save(dict(runs=[report()],events=[],done=[]));store.configure({'jev_key':'apikey_'+('a'*50),'jev_enabled':True})
            process_one(store,lambda k,p:response(p));path=sidecar(store.root,report()['slot'])
            value=json.loads(path.read_text());value['rows'][0]['confidence']=.1;path.write_text(json.dumps(value))
            self.assertNotIn('jev',attach(store.root,report()))
