import copy
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from mobile_server.daily_realtime_performance import select_groups, evaluate_groups, collect_realtime_performance
from mobile_server.realtime_history import RealtimeArchive
from tests.test_daily_performance import daily, factors

SIGNAL='20260904';EVALUATION='20260907'


def run(clock='1450',date=SIGNAL,**changes):
    now=datetime.strptime(date+clock,'%Y%m%d%H%M').replace(tzinfo=ZoneInfo('Asia/Shanghai')).timestamp()
    row=dict(strategy='overnight',ts_code='600000.SH',name='提醒样本',price=10.,quote_at=now-1.)
    value=dict(date=date,slot=date+'-'+clock,kind='screen',status='ready',run_state='complete',
               executor='mac',generated_at=now,message='已完成',strategies=dict(overnight=[row],golden=[]))
    if clock=='1430':value['bottom_volume']=dict(status='empty',matched_count=0,candidates=[],rule_version=2)
    value.update(changes);return value


class Archive:
    def __init__(self,*reports):self.reports={r['slot']:copy.deepcopy(r) for r in reports};self.requests=[]
    def run(self,slot):
        self.requests.append(slot)
        if slot not in self.reports:raise FileNotFoundError()
        value=self.reports[slot]
        if isinstance(value,Exception):raise value
        return value


def evaluate(groups,previous=None,current=None,before=None,after=None):
    return evaluate_groups(groups,SIGNAL,EVALUATION,
        daily(SIGNAL,previous or {'600000.SH':11.}),daily(EVALUATION,current or {'600000.SH':12.}),
        factors(SIGNAL,before or {'600000.SH':1.}),factors(EVALUATION,after or {'600000.SH':1.}))


class DailyRealtimePerformanceTests(unittest.TestCase):
    def test_ai_failure_retains_a_deterministic_realtime_summary_for_older_clients(self):
        from mobile_server.daily import DailyStore,unavailable
        from mobile_server.daily_facts import evidence_hash
        performance=evaluate(select_groups(Archive(run()),SIGNAL))
        evidence=dict(date=EVALUATION,realtime_performance=performance)
        report=dict(schema_version=1,date=EVALUATION,generated_at=1.,evidence=evidence,
                    evidence_sha256=evidence_hash(evidence),analysis=unavailable('AI 输出未通过范围检查'))
        with tempfile.TemporaryDirectory() as folder:
            store=DailyStore(Path(folder));store.write_report(report);saved=store.report(EVALUATION)
        self.assertEqual(saved['analysis']['status'],'unavailable')
        text=saved['analysis']['strategy_view']
        self.assertIn('程序汇总',text);self.assertIn('一夜持股',text)
        self.assertIn('今日等权涨跌+9.09%',text);self.assertIn('提醒价至今收+20.00%',text)
        self.assertIn('未结算',text)
        self.assertEqual(saved['evidence_sha256'],report['evidence_sha256'])
        self.assertIn('AI 输出未通过范围检查',saved['analysis']['risks'])
    def test_latest_completed_yesterday_is_used_once_and_today_is_never_read(self):
        early=run('1430');late=run();today=run(date=EVALUATION)
        early['strategies']['overnight'][0]['ts_code']='600001.SH'
        today['strategies']['overnight'][0]['ts_code']='600002.SH'
        archive=Archive(early,late,today)
        groups=select_groups(archive,SIGNAL)
        result=evaluate(groups);group=result['strategies'][0]
        self.assertEqual(group['source_slot'],SIGNAL+'-1450')
        self.assertEqual(group['selected_count'],1)
        self.assertEqual(group['rows'][0]['ts_code'],'600000.SH')
        self.assertAlmostEqual(group['mean_return_pct'],100/11)
        self.assertAlmostEqual(group['mean_signal_return_pct'],20.)
        self.assertTrue(all(slot.startswith(SIGNAL) for slot in archive.requests))
        self.assertEqual(len(group['source_sha256']),64)

    def test_last_empty_run_is_no_picks_not_an_older_winning_list(self):
        result=evaluate(select_groups(Archive(run('1430'),run(strategies=dict(overnight=[],golden=[]))),SIGNAL))
        group=result['strategies'][0]
        self.assertEqual(group['status'],'no_picks');self.assertEqual(group['selected_count'],0)
        self.assertIsNone(group['mean_return_pct'])

    def test_failed_final_run_uses_last_completed_run_with_explicit_source(self):
        failed=run(status='blocked',run_state='data_incomplete',strategies=dict(overnight=[],golden=[]))
        group=evaluate(select_groups(Archive(run('1445'),failed),SIGNAL))['strategies'][0]
        self.assertEqual(group['source_slot'],SIGNAL+'-1445')
        self.assertIn('14:50',group['message']);self.assertIn('14:45',group['message'])

    def test_bottom_uses_only_1430_even_if_other_two_strategies_failed(self):
        early=run('1430',status='blocked',run_state='data_incomplete',strategies=dict(overnight=[],golden=[]))
        early['bottom_volume']=dict(status='ready',matched_count=25,rule_version=2,
            candidates=[dict(strategy='bottom_volume',ts_code='600000.SH',name='底部样本',price=10.,quote_at=early['generated_at'])])
        final=run();final['bottom_volume']=dict(early['bottom_volume'])
        group=evaluate(select_groups(Archive(early,final),SIGNAL))['strategies'][2]
        self.assertEqual(group['source_slot'],SIGNAL+'-1430');self.assertEqual(group['selected_count'],1)
        self.assertEqual(group['matched_count'],25);self.assertEqual(group['rule_version'],2)

    def test_overlapping_strategies_remain_separate_and_are_not_added_as_account_profit(self):
        report=run();report['strategies']['golden']=[dict(report['strategies']['overnight'][0],strategy='golden')]
        result=evaluate(select_groups(Archive(report),SIGNAL))
        self.assertEqual([g['selected_count'] for g in result['strategies'][:2]],[1,1])
        self.assertNotIn('total_return_pct',result)

    def test_missing_archive_and_failed_strategy_are_unknown_not_zero_candidates(self):
        result=evaluate(select_groups(Archive(),SIGNAL))
        self.assertEqual(result['status'],'unavailable')
        for group in result['strategies']:
            self.assertEqual(group['status'],'unavailable');self.assertIsNone(group['selected_count'])
            self.assertIsNone(group['mean_return_pct'])

    def test_archive_hash_or_schema_failure_does_not_fall_back_to_an_older_positive_list(self):
        archive=Archive(run('1445'));archive.reports[SIGNAL+'-1450']=ValueError('Bad archive hash')
        self.assertEqual(select_groups(archive,SIGNAL)[0]['status'],'unavailable')
        for mutation in ['date','price','quote_at','duplicate','strategy']:
            report=run();row=report['strategies']['overnight'][0]
            if mutation=='date':report['date']=EVALUATION
            elif mutation=='price':row['price']=0.
            elif mutation=='quote_at':row['quote_at']-=600.
            elif mutation=='duplicate':report['strategies']['overnight'].append(dict(row))
            else:row['strategy']='golden'
            with self.subTest(mutation=mutation):
                self.assertEqual(select_groups(Archive(run('1445'),report),SIGNAL)[0]['status'],'unavailable')

    def test_split_adjusts_both_return_bases_and_missing_data_hides_group_averages(self):
        groups=select_groups(Archive(run()),SIGNAL)
        group=evaluate(groups,previous={'600000.SH':10.},current={'600000.SH':5.2},after={'600000.SH':2.})['strategies'][0]
        self.assertAlmostEqual(group['mean_return_pct'],4.)
        self.assertAlmostEqual(group['mean_signal_return_pct'],4.)
        report=run();report['strategies']['overnight'].append(dict(report['strategies']['overnight'][0],ts_code='600001.SH'))
        groups=select_groups(Archive(report),SIGNAL)
        group=evaluate(groups)['strategies'][0]
        self.assertEqual(group['status'],'partial');self.assertEqual(group['settled_count'],1)
        self.assertIsNone(group['mean_return_pct']);self.assertIsNone(group['mean_signal_return_pct'])
        self.assertEqual(group['rows'][1]['status'],'unsettled')

    def test_calendar_and_immutable_archive_are_used_by_real_collector(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);market=root/'market';(market/'raw').mkdir(parents=True)
            calendar=pd.DataFrame(dict(exchange=['SSE']*4,cal_date=[SIGNAL,'20260905','20260906',EVALUATION],is_open=[1,0,0,1]))
            calendar.to_parquet(market/'raw/trade_cal.parquet',index=False)
            daily(SIGNAL,{'600000.SH':11.}).to_parquet(market/'raw/daily.parquet',index=False)
            factors(SIGNAL,{'600000.SH':1.}).to_parquet(market/'raw/adj_factor.parquet',index=False)
            archive=root/'jobs/realtime';archive.mkdir(parents=True)
            RealtimeArchive(archive).collect(dict(runs=[run('1430'),run()],events=[]))
            frames=dict(daily=daily(EVALUATION,{'600000.SH':12.}),adj_factor=factors(EVALUATION,{'600000.SH':1.}))
            result=collect_realtime_performance(root,market,EVALUATION,frames)
            self.assertEqual(result['signal_date'],SIGNAL)
            self.assertEqual(result['strategies'][0]['status'],'complete')
            self.assertEqual(result['strategies'][2]['status'],'no_picks')
            # A subsequent alteration fails the frozen hash; no recomputation.
            path=archive/'run-archive'/(SIGNAL+'-1450.json');path.write_text('{}')
            result=collect_realtime_performance(root,market,EVALUATION,frames)
            self.assertEqual(result['strategies'][0]['status'],'unavailable')
