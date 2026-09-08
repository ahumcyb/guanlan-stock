import tempfile
import unittest
from pathlib import Path
from mobile_server.artifacts import atomic_json
from mobile_server.daily_facts import evidence_hash
from mobile_server.daily_changes import market_changes,selection_changes


class DailyChangesTests(unittest.TestCase):
    def test_market_comparison_requires_matching_prior_evidence_hash(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);before={'stock_count':5000,'turnover_yi':100.,'advancers':2000,'decliners':2500,'breadth':.4,'limit_up':30,'limit_down':10}
            evidence=dict(date='20260904',market=before)
            path=root/'jobs/daily/reports/20260904.json'
            atomic_json(path,dict(schema_version=1,date='20260904',evidence=evidence,evidence_sha256=evidence_hash(evidence)))
            current=dict(before,turnover_yi=150.,advancers=3000,breadth=.5)
            result=market_changes(root,'20260904',current)
            self.assertEqual(result['turnover_change_pct'],50.)
            self.assertEqual(result['advancers_change'],1000)
            self.assertAlmostEqual(result['breadth_change_pp'],10.)
            evidence['market']['turnover_yi']=1.
            atomic_json(path,dict(schema_version=1,date='20260904',evidence=evidence,evidence_sha256='a'*64))
            self.assertIsNone(market_changes(root,'20260904',current))

    def test_added_retained_and_removed_never_claim_unsupported_prior_history(self):
        pick=lambda code:dict(ts_code=code,name=code)
        current=[dict(id='leaders',name='趋势',picks=[pick('000002.SZ'),pick('000003.SZ')]),dict(id='left_rebound',name='左侧',picks=[pick('000004.SZ')])]
        previous=dict(status='available',signal_date='20260904',strategies=[dict(id='leaders',rows=[pick('000001.SZ'),pick('000002.SZ')])])
        result=selection_changes(current,previous,{'leaders':{'000001.SZ':'未满足量能条件'}})
        self.assertEqual([r['ts_code'] for r in result[0]['added']],['000003.SZ'])
        self.assertEqual([r['ts_code'] for r in result[0]['retained']],['000002.SZ'])
        self.assertEqual(result[0]['removed'][0]['reason'],'未满足量能条件')
        self.assertEqual(result[1]['status'],'new_strategy')
        self.assertEqual(result[1]['retained'],[])
        unavailable=selection_changes(current,{'status':'unavailable','strategies':[]},{})
        self.assertTrue(all(r['status']=='unavailable' and not r['added'] for r in unavailable))

    def test_missing_prior_summary_is_unknown_instead_of_zero(self):
        with tempfile.TemporaryDirectory() as folder:self.assertIsNone(market_changes(Path(folder),'20260904',{}))
