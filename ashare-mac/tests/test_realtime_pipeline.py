import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import pandas as pd
from engine.intraday import local_now
from engine.intraday_runner import IntradayProvider,run
from mobile_server.realtime import RealtimeStore,validate_report
from mobile_server import realtime_worker

NOW=local_now().replace(year=2026,month=9,day=7,hour=14,minute=45,second=0,microsecond=0)


def quote(code,timed=True):
    return dict(ts_code=code,name='测试股票',open=10,high=10.5,low=9.9,close=10.4,pre_close=10,
                vol=100000000,amount=1030000000,trade_time='20260907144500' if timed else '20260907')


class PrimaryWithoutTime(IntradayProvider):
    def __init__(self):pass
    def get(self,api,**params):
        if api=='rt_min_daily':raise ValueError('minute source unavailable')
        return pd.DataFrame([quote(code,False) for code in params['ts_code'].split(',')])


class RealtimePipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.codes=[f'{600000+n:06}.SH' for n in range(4001)]
        feature=dict(name='测试股票',date='20260904',observations=60,adjusted=True,last_close=10,
            sum4=40,sum9=87,sum19=175,ma5=9.9,platform_high=11,platform_range=1.1,
            mean_volume5=50000000,float_shares=1900000000)
        self.features=dict(previous='20260904',source_version='test-fixture',open_dates=['20260904','20260907','20260908'],
            features={code:dict(feature) for code in self.codes},warnings=[])

    def tearDown(self):self.tmp.cleanup()

    def test_full_fallback_pipeline_publishes_fenced_result_and_notifies_once(self):
        with patch('engine.intraday_runner.local_now',return_value=NOW), \
             patch('engine.intraday_runner.features_for',return_value=self.features), \
             patch('engine.intraday_runner.sina_quotes',side_effect=lambda codes:[quote(code) for code in codes]):
            report=run(self.root,self.root/'cache',provider=PrimaryWithoutTime())
        self.assertEqual(report['status'],'ready')
        self.assertEqual(report['fresh_count'],4001)
        self.assertEqual(len(report['strategies']['overnight']),10)
        self.assertEqual(report['index_source'],'sina')
        self.assertTrue(any('新浪' in message for message in report['warnings']))
        store=RealtimeStore(self.root,lambda:NOW.timestamp());store.calendar(self.features['open_dates'])
        job=store.claim('mac');self.assertTrue(store.publish(job['lease'],report))
        self.assertFalse(store.publish(job['lease'],report))
        self.assertEqual(len(store.public()['events']),1)
        self.assertNotIn('lease',json.dumps(store.public()))

    def test_missing_time_in_both_sources_blocks_instead_of_publishing_candidates(self):
        with patch('engine.intraday_runner.local_now',return_value=NOW), \
             patch('engine.intraday_runner.features_for',return_value=self.features), \
             patch('engine.intraday_runner.sina_quotes',side_effect=lambda codes:[quote(code,False) for code in codes]):
            report=run(self.root,self.root/'cache',provider=PrimaryWithoutTime())
        self.assertEqual(report['status'],'blocked')
        self.assertEqual(report['failure_code'],'quotes_incomplete')
        self.assertFalse(any(report['strategies'].values()))

    def test_missing_index_timestamp_is_an_explained_blocked_result(self):
        with patch('engine.intraday_runner.local_now',return_value=NOW), \
             patch('engine.intraday_runner.features_for',return_value=self.features), \
             patch('engine.intraday_runner.sina_quotes',side_effect=lambda codes:[quote(code,code!='000300.SH') for code in codes]):
            report=run(self.root,self.root/'cache',provider=PrimaryWithoutTime())
        self.assertEqual(report['status'],'blocked')
        self.assertEqual(report['failure_code'],'index_unavailable')
        self.assertIn('沪深300',report['message'])

    def test_worker_failure_records_stage_without_exception_text_or_lease(self):
        job=dict(id='20260907-1445',date='20260907',previous_date='20260904',kind='screen',lease='private-lease-value')
        def failure(*args,**kwargs):
            kwargs['progress']('history')
            raise ValueError('sensitive-response-must-not-be-persisted')
        with patch('mobile_server.realtime_worker.execute',side_effect=failure), \
             patch('mobile_server.realtime_worker.time.time',return_value=NOW.timestamp()):
            report=realtime_worker.execute_report(self.root,self.root,job)
        self.assertEqual(report['status'],'blocked');self.assertEqual(report['failure_stage'],'history')
        validate_report(report,job,NOW.timestamp())
        text=json.dumps(report)+''.join(p.read_text() for p in (self.root/'diagnostics').glob('*.json'))
        self.assertNotIn('sensitive-response',text);self.assertNotIn(job['lease'],text)
        self.assertIn('ValueError',text)

    def test_optional_diagnostic_storage_failure_does_not_fail_valid_calculation(self):
        job=dict(id='20260907-1445',date='20260907',previous_date='20260904',kind='screen')
        report=dict(status='ready',quote_diagnostics={})
        with patch('mobile_server.realtime_worker.execute',return_value=report), \
             patch('pathlib.Path.mkdir',side_effect=PermissionError('diagnostic directory')):
            self.assertEqual(realtime_worker.execute_report(self.root,self.root,job),report)

    def test_verified_local_history_skips_large_snapshot_download(self):
        from tests.test_remote import manifest
        header=manifest();(self.root/'manifest.json').write_text(json.dumps(header))
        config={'workspace':str(self.root),'ssh_config':'unused-for-ready-local-history'}
        job={'kind':'screen','previous_date':'20260904'}
        with patch('engine.remote.verify_files'),patch('engine.intraday_runner.run',return_value={'status':'ready'}) as compute, \
             patch('mobile_server.realtime_worker.subprocess.Popen') as download:
            self.assertEqual(realtime_worker.execute(self.root,self.root,job,config),{'status':'ready'})
            download.assert_not_called();compute.assert_called_once()
