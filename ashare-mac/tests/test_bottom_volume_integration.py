import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
from engine.intraday import local_now
from engine.intraday_runner import run
from mobile_server.realtime import RealtimeStore,validate_report,validate_bottom
from copy import deepcopy
from tests.test_bottom_volume import run as bottom_result,quote as bottom_quote

NOW=local_now().replace(year=2026,month=9,day=8,hour=14,minute=30,second=0,microsecond=0)


class StocksOnly:
    def quotes(self,codes):
        return [dict(ts_code=c,name='测试股票',open=10.,close=10.4,high=10.5,low=10.,pre_close=10.,
                     vol=250000.,amount=2600000.,trade_time=NOW.strftime('%Y%m%d%H%M%S')) for c in codes]
    def index_quote(self):return None


class BottomVolumeIntegrationTests(unittest.TestCase):
    def test_index_failure_does_not_block_the_independent_1430_strategy_or_its_notification(self):
        feature=dict(name='测试股票',date='20260907',observations=60,adjusted=True,last_close=10.,mean_volume5=100000.,low60=10.)
        features=dict(previous='20260907',source_version='test',open_dates=['20260907','20260908','20260909'],
                      features={f'{600000+i:06}.SH':dict(feature) for i in range(4001)},warnings=[])
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            with patch('engine.intraday_runner.local_now',return_value=NOW),patch('engine.intraday_runner.features_for',return_value=features):
                report=run(root,root/'cache',provider=StocksOnly(),slot_id='20260908-1430')
            self.assertEqual(report['status'],'blocked')
            self.assertEqual(report['bottom_volume']['status'],'ready')
            self.assertEqual(report['bottom_volume']['matched_count'],4001)
            clock=[NOW.timestamp()];store=RealtimeStore(root,lambda:clock[0]);store.calendar(features['open_dates'])
            job=store.claim('mac');self.assertTrue(store.publish(job['lease'],report))
            event=store.public()['events'][0]
            self.assertIn('底部放量',event['title']);self.assertIn('600000',event['body']);self.assertIn('2.50',event['body'])
            self.assertIn('2.5倍',event['body']);self.assertIn('上涨',event['body'])
            self.assertEqual(store.public()['last_bottom']['slot'],'20260908-1430')
            clock[0]=NOW.replace(minute=45).timestamp();later=store.claim('mac')
            ordinary=dict(schema_version=1,date='20260908',previous_date='20260907',generated_at=clock[0],kind='screen',
                          status='ready',strategies={'overnight':[],'golden':[]},reviews=[],warnings=[],message='旧两策略完成')
            self.assertTrue(store.publish(later['lease'],ordinary))
            self.assertEqual(store.public()['last_bottom']['slot'],'20260908-1430')
            with self.assertRaises(ValueError):validate_report(dict(ordinary,bottom_volume=report['bottom_volume']),later,clock[0])

    def test_later_slot_does_not_run_the_1430_only_strategy(self):
        feature=dict(name='测试股票',date='20260907',observations=60,adjusted=True,last_close=10.,mean_volume5=100000.,low60=10.)
        features=dict(previous='20260907',source_version='test',open_dates=['20260907','20260908'],features={'600000.SH':feature},warnings=[])
        with tempfile.TemporaryDirectory() as folder,patch('engine.intraday_runner.local_now',return_value=NOW),patch('engine.intraday_runner.features_for',return_value=features):
            report=run(Path(folder),Path(folder)/'cache',provider=StocksOnly(),slot_id='20260908-1445')
        self.assertNotIn('bottom_volume',report)

    def test_late_index_response_cannot_leave_expired_bottom_candidates_ready(self):
        clock=[NOW]
        class SlowIndex(StocksOnly):
            def index_quote(self):clock[0]=NOW+timedelta(seconds=181);return None
        feature=dict(name='测试股票',date='20260907',observations=60,adjusted=True,last_close=10.,mean_volume5=100000.,low60=10.)
        features=dict(previous='20260907',source_version='test',open_dates=['20260907','20260908'],features={'600000.SH':feature},warnings=[])
        with tempfile.TemporaryDirectory() as folder,patch('engine.intraday_runner.local_now',side_effect=lambda:clock[0]),patch('engine.intraday_runner.features_for',return_value=features):
            report=run(Path(folder),Path(folder)/'cache',provider=SlowIndex(),slot_id='20260908-1430')
        self.assertEqual(report['bottom_volume']['status'],'blocked')
        self.assertEqual(report['bottom_volume']['candidates'],[])

    def test_missing_low_history_is_incomplete_instead_of_zero_matches(self):
        feature=dict(name='测试股票',date='20260907',observations=60,adjusted=True,last_close=10.,mean_volume5=100000.)
        features=dict(previous='20260907',source_version='test',open_dates=['20260907','20260908'],features={'600000.SH':feature},warnings=[])
        with tempfile.TemporaryDirectory() as folder,patch('engine.intraday_runner.local_now',return_value=NOW),patch('engine.intraday_runner.features_for',return_value=features):
            report=run(Path(folder),Path(folder)/'cache',provider=StocksOnly(),slot_id='20260908-1430')
        self.assertEqual(report['bottom_volume']['status'],'blocked')
        self.assertIn('历史',report['bottom_volume']['message'])

    def test_publication_requires_current_rule_positive_change_and_two_point_five_volume(self):
        bottom=bottom_result(one_quote=bottom_quote(vol=250000.))
        self.assertEqual(bottom['matched_count'],1)
        job=dict(id='20260908-1430',date='20260908',previous_date='20260907')
        validate_bottom(bottom,job,NOW.timestamp())
        for field,value in [('volume_multiple',2.499),('change',0.),('change',-1.)]:
            invalid=deepcopy(bottom);invalid['candidates'][0][field]=value
            with self.subTest(field=field,value=value),self.assertRaises(ValueError):
                validate_bottom(invalid,job,NOW.timestamp())
        for version in [None,1,3,True]:
            invalid=deepcopy(bottom);invalid['rule_version']=version
            with self.subTest(version=version),self.assertRaises(ValueError):
                validate_bottom(invalid,job,NOW.timestamp())
