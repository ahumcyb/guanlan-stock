import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from mobile_server.daily import DailyStore, latest_due_date
from mobile_server.realtime import RealtimeStore


DATE='20260904'


class DailyStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.now=datetime(2026,9,4,16,11,tzinfo=ZoneInfo('Asia/Shanghai')).timestamp()
        self.store=DailyStore(self.root,lambda:self.now)
        self.realtime=RealtimeStore(self.root,lambda:self.now)
        self.realtime.calendar([DATE,'20260907'])
        self.realtime.configure({'daily_enabled':True,'daily_ai_enabled':True,'deepseek_key':'test-key-not-production'})
        self.evidence={'date':DATE,'generation':DATE+'T161100-abcdef','data_revision':DATE+'-'+'a'*16,
                       'market':{'stock_count':4001},'strategies':[],'sectors_strong':[],'sectors_weak':[],'warnings':[]}
        self.calls=0

    def tearDown(self):self.tmp.cleanup()

    def ai(self,key,model,evidence):
        self.calls+=1
        self.assertNotIn(key,json.dumps(evidence))
        return {'status':'ready','model':model,'headline':'收盘复盘','market_view':'市场分化',
                'sector_view':'行业分化','strategy_view':'条件观察','watch_next':'观察确认','risks':['研究不代表盈利保证']}

    def test_current_day_waits_for_cutoff_and_unknown_calendar_is_not_a_holiday(self):
        early=datetime(2026,9,4,16,0,tzinfo=ZoneInfo('Asia/Shanghai'))
        self.assertIsNone(latest_due_date([DATE,'20260907'],early.timestamp()))
        self.assertEqual(latest_due_date([DATE,'20260907'],self.now),DATE)
        self.assertIsNone(latest_due_date(['20260903'],self.now))

    def test_valid_report_is_saved_once_and_not_recharged_after_restart(self):
        collect=lambda *args:self.evidence
        self.store.tick(self.root/'market/current',collect=collect,analyze=self.ai)
        self.assertEqual(self.calls,1)
        restarted=DailyStore(self.root,lambda:self.now)
        restarted.tick(self.root/'market/current',collect=collect,analyze=self.ai)
        self.assertEqual(self.calls,1)
        public=restarted.public()
        self.assertEqual(public['latest']['date'],DATE)
        self.assertNotIn('test-key-not-production',json.dumps(public))
        self.assertEqual(len([e for e in self.realtime.state()['events'] if e['kind']=='daily_review']),1)

    def test_missing_closing_receipt_submits_dated_refresh_without_calling_ai(self):
        def missing(*args):raise FileNotFoundError()
        self.store.tick(self.root/'market/current',collect=missing,analyze=self.ai)
        state=self.store.queue.state()
        self.assertEqual(state['expected_as_of'],DATE)
        self.assertEqual(state['action'],'refresh')
        self.assertEqual(self.calls,0)

    def test_pending_ai_after_restart_is_not_automatically_replayed(self):
        def crash(*args):raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):self.store.tick(self.root/'market/current',collect=lambda *a:self.evidence,analyze=crash)
        self.now+=121
        restarted=DailyStore(self.root,lambda:self.now)
        restarted.tick(self.root/'market/current',collect=lambda *a:self.evidence,analyze=self.ai)
        self.assertEqual(self.calls,0)
        self.assertEqual(restarted.public()['latest']['analysis']['status'],'unavailable')
        restarted.request(retry_ai=True)
        restarted.tick(self.root/'market/current',collect=lambda *a:self.evidence,analyze=self.ai)
        self.assertEqual(self.calls,1)

    def test_daily_notification_has_separate_preference_and_longer_delivery_window(self):
        self.realtime.configure({'notification_enabled':False,'daily_notification_enabled':True,
                                 'bark_url':'https://api.day.app/'+'x'*24})
        self.store.tick(self.root/'market/current',collect=lambda *a:self.evidence,analyze=self.ai)
        self.now+=3600
        event,key=self.realtime.take_event()
        self.assertEqual(event['kind'],'daily_review')
        self.assertEqual(event['url'],'guanlan://daily?date='+DATE)

    def test_key_changes_do_not_enable_intraday_ai_or_return_the_key(self):
        changed=self.store.configure({'enabled':True,'deepseek_key':'another-test-key-not-production','model':'deepseek-v4-pro'})
        self.assertTrue(changed['deepseek_configured'])
        self.assertNotIn('another-test-key-not-production',json.dumps(changed))
        self.assertFalse(self.realtime.settings()['ai_enabled'])

    def test_late_initial_start_can_backfill_the_last_closed_day_once(self):
        self.now=datetime(2026,9,7,8,tzinfo=ZoneInfo('Asia/Shanghai')).timestamp()
        def missing(*args):raise FileNotFoundError()
        self.store.tick(self.root/'market/current',collect=missing,analyze=self.ai)
        self.assertEqual(self.store.queue.state()['expected_as_of'],DATE)

    def test_wrong_evidence_day_never_reaches_the_model(self):
        stale=dict(self.evidence,date='20260903')
        self.store.tick(self.root/'market/current',collect=lambda *a:stale,analyze=self.ai)
        self.assertEqual(self.calls,0)
        self.assertEqual(self.store.queue.state()['expected_as_of'],DATE)

    def test_completed_job_waits_briefly_for_its_closing_receipt(self):
        def missing(*args):raise FileNotFoundError()
        self.store.tick(self.root/'market/current',collect=missing,analyze=self.ai)
        job=self.store.queue.state();job.update(status='completed',message='已发布')
        self.store.queue.save(job)
        self.store.tick(self.root/'market/current',collect=missing,analyze=self.ai)
        self.assertEqual(self.store.state()['days'][DATE]['phase'],'queued')
        self.now+=6
        self.store.tick(self.root/'market/current',collect=lambda *a:self.evidence,analyze=self.ai)
        self.assertEqual(self.store.public()['status']['phase'],'ready')
        self.assertEqual(self.calls,1)

    def test_scheduler_health_requires_its_own_recent_pulse(self):
        self.assertFalse(self.store.public()['scheduler_online'])
        self.store.pulse();self.assertTrue(self.store.public()['scheduler_online'])
        self.now+=46;self.assertFalse(self.store.public()['scheduler_online'])

    def test_refresh_facts_rebuilds_settlement_without_duplicate_completion_alert(self):
        self.store.tick(self.root/'market/current',collect=lambda *a:self.evidence,analyze=self.ai)
        self.now+=61;self.store.request(refresh_facts=True)
        changed=dict(self.evidence,performance={'signal_date':'20260903','evaluation_date':DATE,'status':'unavailable'})
        self.store.tick(self.root/'market/current',collect=lambda *a:changed,analyze=self.ai)
        self.assertEqual(self.store.public()['latest']['evidence']['performance'],changed['performance'])
        self.assertEqual(len([e for e in self.realtime.state()['events'] if e['kind']=='daily_review']),1)
        self.assertEqual(self.calls,2)

    def test_manual_retry_after_failed_refresh_creates_a_new_job(self):
        def unavailable(*args):raise ValueError('data incomplete')
        self.store.tick(self.root/'market/current',collect=unavailable)
        old=self.store.queue.claim('mac')
        self.assertTrue(self.store.queue.failed(old['id'],old['lease']))
        self.now+=301
        self.store.request()
        self.store.tick(self.root/'market/current',collect=unavailable)
        new=self.store.queue.state()
        self.assertNotEqual(old['id'],new['id'])
        self.assertEqual(new['status'],'queued')
