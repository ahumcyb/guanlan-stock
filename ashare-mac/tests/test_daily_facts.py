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
            file=root/'current/momentum_60/report.json';file.write_text('{}')
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
            root,market=published_fixture(folder);directory=root/'current/momentum_60'
            report=json.loads((directory/'report.json').read_text());report['stocks'][1]['close']=999.
            raw=json.dumps(report).encode();(directory/'report.json').write_bytes(raw)
            manifest=json.loads((directory/'manifest.json').read_text())
            manifest.update(report_bytes=len(raw),report_sha256=hashlib.sha256(raw).hexdigest())
            (directory/'manifest.json').write_text(json.dumps(manifest))
            with self.assertRaises(ValueError):collect_evidence(root,market/'current',DATE,NOW.timestamp())
