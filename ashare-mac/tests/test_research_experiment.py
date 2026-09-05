import tempfile
import unittest
from pathlib import Path
import numpy as np
from research.experiment import choose_candidate, verify_hashes, block_interval, phase_daily_returns, promotion_checks, compare
from research.prepare import sha, load_constraints
from engine.data import atomic_json


class ResearchExperimentTests(unittest.TestCase):
    def test_source_change_invalidates_frozen_record(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'rules.py';source.write_text('fixed')
            hashes={'rules.py':sha(source)};verify_hashes(root,hashes)
            source.write_text('changed after seeing results')
            with self.assertRaises(ValueError):verify_hashes(root,hashes)

    def test_selection_rejects_best_validation_score_with_failed_training_or_open_position(self):
        ok={'return':.1,'excess_return':.02,'trades':100,'unresolved':0,'baseline_unresolved':0,'win_rate':.6,'information_ratio':1.}
        training={k:dict(ok) for k in ['a','b','c']};validation={k:dict(ok) for k in training}
        training['a']['excess_return']=-.01;validation['a']['information_ratio']=20.
        validation['c']['unresolved']=1;validation['c']['information_ratio']=30.
        selected=choose_candidate(training,validation,['a','b','c'])
        self.assertEqual(selected['strategy_id'],'b')
        self.assertTrue(selected['eligible_in_development'])

    def test_no_eligible_candidate_is_diagnostic_not_promoted(self):
        bad={'return':-.01,'excess_return':-.01,'trades':100,'unresolved':0,'baseline_unresolved':0,'win_rate':.4,'information_ratio':-1.}
        result=choose_candidate({'a':bad},{'a':bad},['a'])
        self.assertFalse(result['eligible_in_development'])

    def test_block_interval_is_reproducible_and_respects_constant_excess(self):
        config={'bootstrap_seed':1,'bootstrap_repeats':100,'bootstrap_block':10}
        self.assertEqual(block_interval(np.full(30,.001),config),[.001,.001])

    def test_incomplete_constraints_cannot_be_consumed(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);atomic_json(root/'manifest.json',{'complete':False})
            with self.assertRaises(ValueError):load_constraints(root,'any',None,[])

    def test_daily_returns_weight_starting_phases_equally(self):
        returns=phase_daily_returns([[100.,200.,220.],[100.,100.,100.]],100.)
        np.testing.assert_allclose(returns,[0.,.5,.05])

    def test_unresolved_stress_or_benchmark_prevents_promotion(self):
        good={'signal_days':70,'trades':100,'return':.1,'win_rate':.6,
              'excess_return':.03,'phase_excess':[.02,.03,.04],'unresolved':0}
        for location in ['baseline','stress','stress_baseline']:
            values={key:dict(good) for key in ['current','baseline','stress','stress_baseline']}
            values[location]['unresolved']=1
            checks=promotion_checks(True,**values,interval=[.001,.002])
            self.assertFalse(all(checks.values()))

    def test_unresolved_development_benchmark_cannot_validate_candidate(self):
        good={'return':.1,'excess_return':.02,'trades':100,'unresolved':0,'baseline_unresolved':1,'win_rate':.6,'information_ratio':1.}
        with self.assertRaises(ValueError):choose_candidate({'a':good},{'a':good},['a'])

    def test_absent_relative_ranking_does_not_unlock_arbitrary_candidate(self):
        unknown={'return':.1,'excess_return':None,'trades':100,'unresolved':1,'baseline_unresolved':0,'win_rate':.6,'information_ratio':None}
        with self.assertRaises(ValueError):choose_candidate({'a':unknown},{'a':unknown},['a'])

    def test_empty_reference_universe_cannot_produce_valid_relative_ranking(self):
        result={'equity':[{'date':'20260105'}],'daily_returns':[0.],
                'summary':{'unresolved':0,'trades':0}}
        self.assertIsNone(compare(result,result))
        self.assertFalse(result['summary']['relative_valid'])
        self.assertIsNone(result['summary']['information_ratio'])

    def test_empty_candidate_cannot_rank_against_a_traded_reference(self):
        result={'equity':[{'date':'20260105'}],'daily_returns':[0.],
                'summary':{'unresolved':0,'trades':0,'return':0.,'win_rate':None}}
        baseline={'equity':[{'date':'20260105'}],'daily_returns':[-.01],
                  'summary':{'unresolved':0,'trades':5}}
        self.assertIsNone(compare(result,baseline))
        with self.assertRaises(ValueError):
            choose_candidate({'a':result['summary']},{'a':result['summary']},['a'])
