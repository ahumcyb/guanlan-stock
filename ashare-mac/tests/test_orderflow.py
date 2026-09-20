import unittest
from datetime import datetime
from zoneinfo import ZoneInfo
import pandas as pd
from engine.orderflow import decode_flow, decode_replay, apply_evidence, prescreen
from engine.datta import DattaError
DAY='20260918'
def stamp(day,hour=0):return datetime.strptime(day,'%Y%m%d').replace(tzinfo=ZoneInfo('Asia/Shanghai'),hour=hour).timestamp()*1000

def flow():
    return {'code':1,'data':{'symbol':'000001','market':'sz','tradeDay':stamp(DAY),
      'minTime':stamp(DAY,15),'lastPx':10.,'superTurnoverIn':60e6,'superTurnoverOut':40e6,
      'largeTurnoverIn':80e6,'largeTurnoverOut':50e6,'mainTurnoverIn':140e6,
      'mainTurnoverOut':90e6,'netTurnover':50e6,'RatioMain':.1}}
def history():return {'code':1,'data':[{'tradeDay':stamp('20260917'),'netTurnover':-1e6},{'tradeDay':stamp('20260916'),'netTurnover':2e6}]}
def bar():return dict(ts_code='000001.SZ',trade_date=DAY,close=10.,pre_close=9.8,high=10.1,low=9.7,vol=500000.,amount=500000.)
def replay():
    return {'date':int(DAY),'segments':[{'type':'tick','date':int(DAY),'data':[
      {'time':92500,'price':9.8,'volume':1e6,'prev_close':9.8},
      {'time':93000,'price':9.8,'volume':2e6},
      {'time':143000,'price':9.99,'volume':40e6},
      {'time':150000,'price':10.,'volume':50e6}]}]}
class OrderflowTests(unittest.TestCase):
    def test_units_and_explicit_dates(self):
        r=decode_flow(flow(),history(),bar(),['20260916','20260917',DAY])
        self.assertAlmostEqual(r['flow_net_ratio'],.1);self.assertEqual(r['flow_positive_days'],2);self.assertEqual(r['flow_net3'],51e6)
        r=decode_replay(replay(),bar());self.assertAlmostEqual(r['flow_late_volume'],.2);self.assertAlmostEqual(r['flow_late_return'],10/9.99-1)
    def test_stale_receipt_time_cannot_replace_business_date(self):
        for field,value in [('tradeDay',stamp('20260917')),('minTime',stamp(DAY,14)),('RatioMain',10),('lastPx',11)]:
            p=flow();p['data'][field]=value;p['currentTime']=stamp(DAY,16)
            with self.subTest(field=field),self.assertRaises(DattaError):decode_flow(p,history(),bar(),['20260916','20260917',DAY])
        for rows in [history()['data'][:1],history()['data']*2]:
            with self.assertRaises(DattaError):decode_flow(flow(),{'code':1,'data':rows},bar(),['20260916','20260917',DAY])
    def test_replay_partial_updates_and_incomplete_volume(self):
        p=replay();p['segments'][0]['data'].insert(3,{'time':143003,'bid_vol':123})
        self.assertAlmostEqual(decode_replay(p,bar())['flow_late_volume'],.2)
        for change in ['date','missing_close','volume','price','reset','anchor']:
            p=replay();rows=p['segments'][0]['data']
            if change=='date':p['date']=20260917
            if change=='missing_close':rows.pop()
            if change=='volume':rows[-1]['volume']=49e6
            if change=='price':rows[-1]['price']=9.9
            if change=='reset':rows.insert(3,{'time':144000,'volume':1})
            if change=='anchor':rows[2]['time']=140000
            with self.subTest(change=change),self.assertRaises(DattaError):decode_replay(p,bar())
    def test_missing_flow_and_partial_run_have_no_picks(self):
        x=pd.DataFrame([dict(**bar(),eligible=True,confirmed=True,watch=True,setup=True,score=90,
            price=100,ma20=99,ret1=.02,ret5=.03,extension=.01,close_position=.8,
            amount20=400000,breadth=.6,momentum_constraints_ok=True,up_limit=11,down_limit=9,
            atr=.02,low5=9.7,liquidity_rank=.9)])
        ids=prescreen(x,DAY);self.assertEqual(ids,['000001.SZ'])
        evidence={**decode_flow(flow(),history(),bar(),['20260916','20260917',DAY]),**decode_replay(replay(),bar())}
        for complete,data,expected in [(True,{},False),(False,{'000001.SZ':evidence},False),(True,{'000001.SZ':evidence},True)]:
            r=apply_evidence(x.copy(),DAY,ids,data,complete);self.assertEqual(bool(r.confirmed.iloc[0]),expected);self.assertTrue(r.score.between(0,100).all())
        x['trade_date']='20260917';self.assertFalse(apply_evidence(x,DAY,ids,{'000001.SZ':evidence},True).confirmed.any())
if __name__=='__main__':unittest.main()

class RealtimeFlowTests(unittest.TestCase):
    def inputs(self):
        from engine.orderflow_intraday import run_flow
        now=datetime.strptime(DAY+'143000','%Y%m%d%H%M%S').replace(tzinfo=ZoneInfo('Asia/Shanghai'))
        f={'000001.SZ':dict(name='测试',date='20260917',observations=60,adjusted=True,last_close=9.8,amount20=4e8,sum19=185.,mean_volume5=40e6)}
        q=[dict(ts_code='000001.SZ',name='测试',close=10.,pre_close=9.8,high=10.01,low=9.7,vol=50e6,amount=500e6,quote_at=now.timestamp(),change=(10/9.8-1)*100,time_basis='provider_updated_at')]
        return now,f,q
    def test_1430_uses_dated_fresh_flow_and_not_closing_replay(self):
        from engine.orderflow_intraday import run_flow
        from mobile_server.realtime import validate_orderflow,RealtimeStore
        from tempfile import TemporaryDirectory
        now,f,q=self.inputs();calls=[]
        class Client:
            def transport(self,path,params):
                calls.append(path)
                if path.endswith('history'):return history()
                p=flow();p['data']['minTime']=now.timestamp()*1000;return p
        r=run_flow(f,q,['20260916','20260917',DAY],'20260917',Client(),lambda:now)
        self.assertEqual(r['status'],'ready');self.assertEqual(len(r['candidates']),1)
        self.assertFalse(any('/d3/' in c for c in calls))
        job=dict(id=DAY+'-1430',date=DAY,previous_date='20260917')
        validate_orderflow(r,job,now.timestamp())
        with self.assertRaises(ValueError):validate_orderflow(r,dict(job,id=DAY+'-1445'),now.timestamp())
        with self.assertRaises(ValueError):validate_orderflow(r,job,now.timestamp()+181)
        with TemporaryDirectory() as d:
            store=RealtimeStore(d,lambda:now.timestamp());state={'events':[]}
            report=dict(slot=DAY+'-1430',date=DAY,kind='screen',status='blocked',orderflow=r,message='其他策略缺指数')
            store.result_event(state,report);store.result_event(state,report)
            flow_events=[e for e in state['events'] if e['dedup'].endswith('-orderflow')]
            self.assertEqual(len(flow_events),1);self.assertEqual(flow_events[0]['run_id'],DAY+'-1430')
    def test_missing_history_or_expired_flow_is_incomplete_not_zero(self):
        from engine.orderflow_intraday import run_flow
        now,f,q=self.inputs()
        for kind in ['missing','old']:
            class Client:
                def transport(self,path,params):
                    if path.endswith('history'):return history() if kind=='old' else {'code':1,'data':[]}
                    p=flow();p['data']['minTime']=stamp(DAY,14);return p
            r=run_flow(f,q,['20260916','20260917',DAY],'20260917',Client(),lambda:now)
            self.assertEqual(r['status'],'blocked');self.assertEqual(r['candidates'],[])
    def test_batch_prescreen_keeps_sub_three_percent_flow_candidates(self):
        from engine.d101_batch import potential_codes
        now,f,q=self.inputs();q[0]['change']=2.04
        f['000001.SZ']['low60']=5
        self.assertIn('000001.SZ',potential_codes({'000001.SZ':q[0]},f,now,True))

class OrderflowRegressionTests(unittest.TestCase):
    def test_transport_truncation_is_incomplete_and_missing_references_are_not_empty(self):
        from engine.orderflow import collect_daily
        from http.client import IncompleteRead
        x=pd.DataFrame([dict(**bar(),eligible=True,confirmed=True,watch=True,setup=True,score=90,
            price=100,ma20=99,ret1=.02,ret5=.03,extension=.01,close_position=.8,
            amount20=400000,breadth=.6,momentum_constraints_ok=True,up_limit=11,down_limit=9,
            atr=.02,low5=9.7,liquidity_rank=.9)])
        class Broken:
            def transport(self,*args):raise IncompleteRead(b'partial')
        result,status=collect_daily(x.copy(),DAY,['20260916','20260917',DAY],Broken())
        self.assertEqual(status['status'],'incomplete');self.assertFalse(result.confirmed.any())
        x['momentum_constraints_ok']=False
        result,status=collect_daily(x,DAY,['20260916','20260917',DAY],Broken())
        self.assertEqual(status['status'],'incomplete');self.assertIn('_baseline',status['failures'])
    def test_batch_boundary_is_wider_than_final_rule(self):
        from engine.d101_batch import potential_codes
        from engine.orderflow_intraday import flow_pool
        now,f,q=RealtimeFlowTests().inputs();f['000001.SZ']['last_close']=10.;f['000001.SZ']['low60']=5.
        q[0].update(close=10.029,pre_close=10.,high=10.03,low=10.,amount=500e6)
        self.assertEqual(flow_pool(f,q,'20260917'),[])
        self.assertIn('000001.SZ',potential_codes({'000001.SZ':q[0]},f,now,True))
        q[0]['close']=10.031;q[0]['high']=10.031
        self.assertEqual(flow_pool(f,q,'20260917'),['000001.SZ'])
    def test_incomplete_daily_selection_stays_unavailable_in_settlement(self):
        from tests.test_daily_performance import saved_snapshot,daily,factors,SIGNAL_DATE,EVALUATION_DATE
        from mobile_server.daily_performance import evaluate_selections
        s=saved_snapshot({});s['strategies'][-1].update(id='left_rebound')
        s['strategies'].append(dict(id='orderflow',name='大单承接',picks=[],data_status='incomplete'))
        d0=daily(SIGNAL_DATE,{'000001.SZ':10});d1=daily(EVALUATION_DATE,{'000001.SZ':11})
        r=evaluate_selections(s,d0,d1,factors(SIGNAL_DATE,{'000001.SZ':1}),factors(EVALUATION_DATE,{'000001.SZ':1}),EVALUATION_DATE)
        self.assertEqual(r['strategies'][-1]['status'],'unavailable')

class StrategyCompatibilityTests(unittest.TestCase):
    def test_v1_daily_view_preserves_original_and_rehashes_projection(self):
        import copy
        from mobile_server.api import legacy_daily
        from mobile_server.daily_facts import evidence_hash
        evidence=dict(selection_changes=[dict(id=k) for k in ['leaders','pullback','golden_pit','left_rebound','orderflow']],strategies=[dict(id=k) for k in ['leaders','pullback','golden_pit','left_rebound','orderflow']],
            performance=dict(strategies=[dict(id='orderflow')],new_strategy_ids=['orderflow']))
        report=dict(evidence=evidence,evidence_sha256=evidence_hash(evidence));original=copy.deepcopy(report)
        projected=legacy_daily(dict(latest=report))['latest']
        self.assertEqual(report,original);self.assertEqual(len(projected['evidence']['strategies']),4)
        self.assertEqual({g['id'] for g in projected['evidence']['strategies']},{g['id'] for g in projected['evidence']['selection_changes']})
        self.assertEqual(projected['evidence_sha256'],evidence_hash(projected['evidence']))
    def test_three_supported_strategy_sets_and_duplicate_rejection(self):
        from mobile_server.artifacts import valid_strategy_group,STRATEGIES,PREVIOUS_STRATEGIES,HISTORICAL_STRATEGIES
        for ids in [STRATEGIES,PREVIOUS_STRATEGIES,HISTORICAL_STRATEGIES]:self.assertTrue(valid_strategy_group(ids))
        self.assertFalse(valid_strategy_group([*STRATEGIES,'orderflow']))

class MinuteReplayTests(unittest.TestCase):
    def test_dated_minutes_require_full_grid_and_matching_daily_totals(self):
        from engine.orderflow import decode_minutes
        rows=[dict(ts_code='000001.SZ',time=f'2026-09-18T{m//60:02}:{m%60:02}:00+08:00',close=10.,vol=50e6/240,amount=500e6/240)
              for m in list(range(571,691))+list(range(781,901))]
        r=decode_minutes(rows,bar());self.assertAlmostEqual(r['flow_late_volume'],.125)
        self.assertEqual(r['replay_source'],'datta_d6_min1')
        for bad in [rows[:-1],rows+[rows[0]],[dict(r,time=r['time'].replace('09-18','09-17')) for r in rows],[dict(r,vol=r['vol']*.8) for r in rows]]:
            with self.assertRaises(DattaError):decode_minutes(bad,bar())
    def test_close_publication_one_second_later_is_valid_but_not_arbitrary_afterhours(self):
        p=replay();p['segments'][0]['data'][-1]['time']=150001
        self.assertAlmostEqual(decode_replay(p,bar())['flow_late_volume'],.2)
        p['segments'][0]['data'][-1]['time']=153000
        with self.assertRaises(DattaError):decode_replay(p,bar())

class SameSourceRetryTests(unittest.TestCase):
    def test_transient_http_failure_retries_once_and_recovers(self):
        from engine.orderflow_intraday import run_flow
        from http.client import IncompleteRead
        now,f,q=RealtimeFlowTests().inputs()
        class Client:
            calls=0
            def transport(self,path,params):
                self.calls+=1
                if self.calls==1:raise IncompleteRead(b'partial')
                if path.endswith('history'):return history()
                p=flow();p['data']['minTime']=now.timestamp()*1000;return p
        client=Client();r=run_flow(f,q,['20260916','20260917',DAY],'20260917',client,lambda:now)
        self.assertEqual(r['status'],'ready');self.assertEqual(client.calls,3)
    def test_lost_source_ownership_is_not_retried(self):
        from engine.orderflow_intraday import run_flow
        from engine.datta import DattaUnavailable
        now,f,q=RealtimeFlowTests().inputs()
        class Client:
            calls=0
            def transport(self,*args):self.calls+=1;raise DattaUnavailable('lost source lease')
        client=Client();r=run_flow(f,q,['20260916','20260917',DAY],'20260917',client,lambda:now)
        self.assertEqual(r['status'],'blocked');self.assertEqual(client.calls,1)
