import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from tests.test_close_proof import frames,DATE,NOW
from engine.close_proof import make_attestation
from mobile_server.artifacts import STRATEGIES,atomic_json
from mobile_server.daily_facts import collect_evidence


def published_fixture(folder):
    root=Path(folder)/'reports';root.mkdir()
    market=Path(folder)/'market';revision=DATE+'-'+'a'*16
    data=market/'releases'/revision;(data/'raw').mkdir(parents=True)
    generation=DATE+'T161100-abcdef';report_root=root/'releases'/generation
    (root/'current').symlink_to(Path('releases')/generation)
    (market/'current').symlink_to(Path('releases')/revision)
    values=frames();proof=make_attestation(DATE,values,NOW)
    atomic_json(data/'manifest.json',{'as_of':DATE,'revision':revision})
    for name,value in values.items():value.to_parquet(data/'raw'/(name+'.parquet'),index=False)
    values['daily'][['ts_code']].assign(name='测试',industry='测试行业',list_date='20000101').to_parquet(data/'raw/stock_basic.parquet',index=False)
    for strategy in STRATEGIES:
        stocks=[{'ts_code':code,'state':'排除'} for code in values['daily'].ts_code]
        stocks[1].update(state='入选',name='测试',industry='测试行业',trade_date=DATE,close=10.,change=0.,score=90.,rank=1)
        report={'as_of':DATE,'data_revision':revision,'strategy_id':strategy,'strategy_name':strategy,
                'stocks':stocks,'shortlist_count':1,'confirmed_count':1,'watching_count':0,'breadth':.5,
                'last_update':{'forced_latest_date':DATE,'close_attestation':proof,'failures':[]}}
        raw=json.dumps(report).encode();folder=report_root/strategy;folder.mkdir(parents=True)
        (folder/'report.json').write_bytes(raw)
        atomic_json(folder/'manifest.json',{'generation':generation,'as_of':DATE,'strategy':strategy,
                    'data_revision':revision,'stock_count':len(stocks),'report_bytes':len(raw),'report_sha256':hashlib.sha256(raw).hexdigest()})
    atomic_json(root/'jobs/closing-receipts'/(DATE+'.json'),{'schema_version':1,'date':DATE,'generation':generation,
                'data_revision':revision,'close_attestation':proof,'published_at':NOW.timestamp(),'job_id':'receipt'})
    return root,market


class DailyFactsTests(unittest.TestCase):
    def test_collector_settles_saved_previous_picks_and_preserves_retired_strategy(self):
        import pandas as pd
        from mobile_server.artifacts import HISTORICAL_STRATEGIES
        from mobile_server.selection_snapshots import save_snapshot
        with tempfile.TemporaryDirectory() as folder:
            root,market=published_fixture(folder);raw=market/'current/raw'
            today=pd.read_parquet(raw/'daily.parquet');code=today.iloc[2].ts_code
            prior=today.iloc[[2]].copy();prior['trade_date']='20260903';prior['close']=8.
            pd.concat([prior,today],ignore_index=True).to_parquet(raw/'daily.parquet',index=False)
            factors=pd.read_parquet(raw/'adj_factor.parquet');old=factors.iloc[[2]].copy();old['trade_date']='20260903'
            pd.concat([old,factors],ignore_index=True).to_parquet(raw/'adj_factor.parquet',index=False)
            pd.DataFrame({'exchange':['SSE','SSE'],'cal_date':['20260903',DATE],'is_open':[1,1]}).to_parquet(raw/'trade_cal.parquet',index=False)
            groups=[dict(id=s,name=s,picks=[dict(ts_code=code,name='昨日精选',close=8.,rank=1)]) for s in HISTORICAL_STRATEGIES]
            save_snapshot(root,'20260903','20260903T161100-abcdef','20260903-'+'b'*16,groups)
            from tests.test_daily_realtime_performance import run
            from mobile_server.realtime_history import RealtimeArchive
            archive=root/'jobs/realtime';archive.mkdir(parents=True)
            realtime=run(date='20260903');realtime['strategies']['overnight'][0].update(ts_code=code,price=9.)
            RealtimeArchive(archive).collect(dict(runs=[realtime],events=[]))
            facts=collect_evidence(root,market/'current',DATE,NOW.timestamp());result=facts['performance']
            self.assertEqual(result['status'],'available')
            self.assertEqual(result['signal_date'],'20260903')
            self.assertEqual(result['new_strategy_ids'],['left_rebound'])
            self.assertEqual(result['strategies'][-1]['id'],'momentum_60')
            for group in result['strategies']:
                self.assertEqual(group['rows'][0]['ts_code'],code)
                self.assertEqual(group['mean_return_pct'],25.)
            self.assertNotEqual(facts['strategies'][0]['picks'][0]['ts_code'],code)
            realtime=facts['realtime_performance']['strategies'][0]
            self.assertEqual(realtime['mean_return_pct'],25.)
            self.assertAlmostEqual(realtime['mean_signal_return_pct'],100/9)
            self.assertEqual(realtime['source_slot'],'20260903-1450')

    def test_amount_units_counts_and_four_strategy_binding(self):
        with tempfile.TemporaryDirectory() as folder:
            root,market=published_fixture(folder)
            facts=collect_evidence(root,market/'current',DATE,NOW.timestamp())
            self.assertEqual(facts['market']['stock_count'],4001)
            self.assertEqual(facts['market']['unchanged'],4001)
            self.assertEqual(facts['market']['turnover_yi'],4001.)
            self.assertEqual(len(facts['strategies']),4)
            self.assertEqual(facts['sectors_strong'][0]['name'],'测试行业')
            self.assertNotIn('last_update',json.dumps(facts))

    def test_mismatched_report_or_day_proof_cannot_feed_ai(self):
        with tempfile.TemporaryDirectory() as folder:
            root,market=published_fixture(folder)
            file=root/'current/left_rebound/report.json';file.write_text('{}')
            with self.assertRaises(ValueError):collect_evidence(root,market/'current',DATE,NOW.timestamp())

    def test_receipt_survives_current_pointer_advancing_but_remains_bound_to_its_data(self):
        with tempfile.TemporaryDirectory() as folder:
            root,market=published_fixture(folder)
            (root/'current').unlink();(root/'current').symlink_to('releases/unrelated')
            result=collect_evidence(root,market/'current',DATE,NOW.timestamp())
            self.assertEqual(result['date'],DATE)
            with self.assertRaises((ValueError,FileNotFoundError)):
                collect_evidence(root,market/'current','20260907',NOW.timestamp())

    def test_self_consistent_report_hash_does_not_hide_a_wrong_candidate_price(self):
        with tempfile.TemporaryDirectory() as folder:
            root,market=published_fixture(folder);directory=root/'current/left_rebound'
            report=json.loads((directory/'report.json').read_text());report['stocks'][1]['close']=999.
            raw=json.dumps(report).encode();(directory/'report.json').write_bytes(raw)
            manifest=json.loads((directory/'manifest.json').read_text())
            manifest.update(report_bytes=len(raw),report_sha256=hashlib.sha256(raw).hexdigest())
            (directory/'manifest.json').write_text(json.dumps(manifest))
            with self.assertRaises(ValueError):collect_evidence(root,market/'current',DATE,NOW.timestamp())
