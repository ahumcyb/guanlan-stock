import json
import unittest
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from engine.d101_batch import BatchFallback, BatchCapture, decode_batch_row, capture_batch, potential_codes, verify_batch,compatible

NOW=datetime(2026,9,9,14,30,tzinfo=ZoneInfo('Asia/Shanghai'))


def row(code='SH600000',**changes):
    value=dict(code=code,name='测试股票',decimal_num=2,volume_unit_flag=1,trade_date=20260909,
               price=1040,open_price=1000,high=1050,low=990,pre_close=1000,volume=2000000,amount=2080000000)
    value.update(changes);return value


def feature(**changes):
    value=dict(date='20260908',name='测试股票',adjusted=True,observations=60,last_close=10.,
               mean_volume5=100000000.,low60=9.95)
    value.update(changes);return value


def d6_quote(code='600000.SH',**changes):
    value=dict(ts_code=code,name='测试股票',open=10.,high=10.5,low=9.9,close=10.4,pre_close=10.,
               vol=200000000.,amount=2080000000.,trade_time='20260909',updated_at=NOW.isoformat(),quote_source='datta')
    value.update(changes);return value


class Socket:
    def __init__(self,frames):self.frames=iter(frames);self.sent=[];self.closed=False
    def __enter__(self):return self
    def __exit__(self,*args):self.closed=True
    def send(self,value):self.sent.append(json.loads(value))
    def recv(self,timeout):
        try:return json.dumps(next(self.frames))
        except StopIteration:raise TimeoutError()


def envelope(rows,ts=None):return dict(ts=ts or NOW.timestamp()*1000,list=[dict(type='snapshot',data=rows)])


class D101BatchTests(unittest.TestCase):
    def test_one_cent_reference_error_on_a_low_price_stock_cannot_hide_a_match(self):
        from engine.intraday import normalize_quote,screen
        code='600000.SH'
        f=feature(last_close=1.,mean_volume5=1000000.,low60=.5,sum4=3.9,sum9=8.6,sum19=17.8,
                  ma5=.97,platform_range=1.04,platform_high=1.)
        d6=normalize_quote(d6_quote(close=1.03,pre_close=1.,open=1.,high=1.04,low=.99,
                                    vol=2500000.,amount=2550000.),NOW)
        batch=dict(d6,pre_close=1.01)
        self.assertTrue(screen({code:f},[d6],dict(change=0.,quote_at=NOW.timestamp()),NOW,'20260908')['overnight'])
        self.assertIn(code,potential_codes({code:batch},{code:f},NOW,False))
        self.assertFalse(compatible(batch,d6))

    def test_broad_filter_preserves_rule_matches_at_edges_and_does_not_cut_to_ten(self):
        from engine.intraday import normalize_quote,screen,bottom_volume_screen
        features={};quotes=[];batch={}
        cases=[(change,multiple,distance) for change in [.001,2.999999999,3.,4.,5.,5.000000001,12.]
               for multiple in [1.,1.5,2.5,3.] for distance in [0.,.05,.10]]
        index=dict(change=0.,quote_at=NOW.timestamp())
        expected=set()
        for i,(change,multiple,distance) in enumerate(cases):
            code=f'{600000+i}.SH';price=10*(1+change/100)
            f=feature(low60=price/(1+distance),sum4=39.,sum9=86.,sum19=178.,ma5=9.7,
                      platform_range=1.04,platform_high=10.,float_shares=800000000.)
            q=normalize_quote(d6_quote(code,close=price,high=price,vol=multiple*1e8,amount=multiple*1e8*price),NOW)
            features[code]=f;quotes.append(q);batch[code]=q
            matches=screen({code:f},[q],index,NOW,'20260908')
            bottom=bottom_volume_screen({code:f},[q],NOW,'20260908')
            if any(matches.values()) or bottom['matched_count']:expected.add(code)
        self.assertGreater(len(expected),10)
        self.assertTrue(expected<=potential_codes(batch,features,NOW,True))

    def test_runner_uses_batch_coverage_but_only_d6_candidates_and_source_times(self):
        from engine.intraday_runner import run
        from engine.intraday import normalize_quote
        features={f'{600000+i}.SH':feature() for i in range(100)}
        context=dict(features=features,previous='20260908',source_version='fixture',warnings=[],open_dates=['20260909'])
        class Provider:
            batch_enabled=True
            quote_diagnostics=dict(provider='datta_d6',mode='d101_batch_verified',coverage_count=100,
                                   batch_count=100,batch_received_at=NOW.timestamp(),verified_count=1)
            def quotes(self,codes):raise AssertionError('Full quote path used')
            def screen_quotes(self,features,include_bottom):
                assert include_bottom
                return [d6_quote(vol=250000000.,amount=2600000000.)]
            def index_quote(self):return d6_quote('000300.SH')
        with tempfile.TemporaryDirectory() as directory,\
             patch('engine.intraday_runner.features_for',return_value=context),\
             patch('engine.intraday_runner.local_now',return_value=NOW):
            report=run(Path(directory),Path(directory),provider=Provider(),slot_id='20260909-1430')
        self.assertEqual(report['status'],'ready')
        self.assertEqual(report['quote_count'],100)
        self.assertEqual(report['batch_quote_count'],100)
        self.assertEqual(report['fresh_count'],1)
        self.assertEqual(report['bottom_volume']['matched_count'],1)
        candidate=report['bottom_volume']['candidates'][0]
        self.assertEqual(candidate['quote_at'],normalize_quote(d6_quote(),NOW)['quote_at'])
        self.assertEqual(candidate['time_basis'],'provider_updated_at')

    def test_stock_day_precision_and_volume_unit_are_explicit(self):
        normal=decode_batch_row(row(),'20260909')
        science=decode_batch_row(row(code='SH688660',volume=200000000,volume_unit_flag=0),'20260909')
        self.assertEqual(normal['close'],10.4);self.assertEqual(normal['vol'],200000000)
        self.assertEqual(science['vol'],normal['vol'])
        self.assertNotIn('quote_at',normal);self.assertNotIn('updated_at',normal)
        self.assertEqual(decode_batch_row(row(price=10400,high=10500,low=9900,open_price=10000,pre_close=10000,decimal_num=3),'20260909')['close'],10.4)

    def test_wrong_date_missing_units_nulls_and_bad_numbers_are_not_live_quotes(self):
        for values in [dict(trade_date=20260908),dict(decimal_num=None),dict(volume_unit_flag=2),
                       dict(price=None),dict(volume=-1),dict(amount=float('inf')),dict(high=1000)]:
            with self.subTest(values=values),self.assertRaises(BatchFallback):decode_batch_row(row(**values),'20260909')

    def test_one_request_merges_partial_frames_and_closes_connection(self):
        complete=row();first={k:v for k,v in complete.items() if k!='amount'}
        sock=Socket([envelope([first]),envelope([dict(code='SH600000',amount=complete['amount'])])]);options=[]
        def connect(uri,**kwargs):options.append((uri,kwargs));return sock
        capture=capture_batch('http://127.0.0.1:8080',['600000.SH'],'20260909',connector=connect,clock=lambda:NOW.timestamp())
        self.assertEqual(len(capture.rows),1);self.assertEqual(len(sock.sent),1)
        self.assertEqual(sock.sent[0]['codes'],['SH600000']);self.assertIn('trade_date',sock.sent[0]['fields'])
        self.assertTrue(sock.closed);self.assertIsNone(options[0][1]['proxy'])
        self.assertLessEqual(options[0][1]['max_size'],8*1024*1024)

    def test_date_change_does_not_reuse_old_day_fields(self):
        sock=Socket([envelope([row(trade_date=20260908)]),envelope([dict(code='SH600000',trade_date=20260909,price=1040)])])
        capture=capture_batch('http://127.0.0.1:8080',['600000.SH'],'20260909',connector=lambda *a,**kw:sock,clock=lambda:NOW.timestamp())
        self.assertEqual(capture.rows,{})

    def test_conflicting_rows_and_null_update_cannot_reuse_a_valid_value(self):
        for frames in [[envelope([row(),row(price=1041)])],
                       [envelope([row()]),envelope([dict(code='SH600000',amount=None)])]]:
            sock=Socket(frames)
            capture=capture_batch('http://127.0.0.1:8080',['600000.SH','600001.SH'],'20260909',connector=lambda *a,**kw:sock,clock=lambda:NOW.timestamp())
            self.assertNotIn('600000.SH',capture.rows)

    def test_stale_transport_is_rejected_without_inventing_quote_time(self):
        sock=Socket([envelope([row()],(NOW.timestamp()-60)*1000)])
        with self.assertRaises(BatchFallback):
            capture_batch('http://127.0.0.1:8080',['600000.SH'],'20260909',connector=lambda *a,**kw:sock,clock=lambda:NOW.timestamp())

    def test_broad_prescreen_includes_bottom_and_all_old_strategy_price_band(self):
        values={'600000.SH':decode_batch_row(row(),'20260909'),
                '600001.SH':decode_batch_row(row(code='SH600001',price=1020,volume=2600000,amount=2652000000),'20260909')}
        features={code:feature() for code in values}
        self.assertEqual(potential_codes(values,features,NOW,True),set(values))
        self.assertEqual(potential_codes(values,features,NOW,False),{'600000.SH'})

    def test_final_result_contains_only_d6_records_with_original_stock_time(self):
        capture=BatchCapture({'600000.SH':decode_batch_row(row(),'20260909')},NOW.timestamp(),{})
        class Client:
            def quotes(self,codes):return [d6_quote(code) for code in codes]
        rows,diagnostics=verify_batch(capture,['600000.SH'],{'600000.SH':feature()},Client(),NOW,True,clock=lambda:NOW)
        self.assertEqual(rows,[d6_quote()]);self.assertEqual(diagnostics['mode'],'d101_batch_verified')
        self.assertEqual(diagnostics['batch_count'],1);self.assertEqual(diagnostics['verified_count'],1)

    def test_missing_candidate_verification_or_frozen_feed_causes_fallback(self):
        capture=BatchCapture({'600000.SH':decode_batch_row(row(),'20260909')},NOW.timestamp(),{})
        for result in [[],[d6_quote(vol=400000000.,amount=4160000000.)],
                       [d6_quote(updated_at='2026-09-09T14:20:00+08:00')]]:
            class Client:
                def quotes(self,codes):return result
            with self.subTest(result=result),self.assertRaises(BatchFallback):
                verify_batch(capture,['600000.SH'],{'600000.SH':feature()},Client(),NOW,True,clock=lambda:NOW)

    def test_small_partial_d6_failure_is_retried_once_before_full_fallback(self):
        from unittest.mock import Mock
        batch={f'{600000+i}.SH':decode_batch_row(row(code=f'SH{600000+i}'),'20260909') for i in range(20)}
        codes=sorted(batch);client=Mock()
        client.quotes.side_effect=[[d6_quote(code) for code in codes[1:]],[d6_quote(codes[0])]]
        result,diagnostics=verify_batch(BatchCapture(batch,NOW.timestamp(),{}),codes,
            {code:feature() for code in codes},client,NOW,True,clock=lambda:NOW)
        self.assertEqual(len(result),20)
        self.assertEqual(client.quotes.call_args_list[-1].args[0],[codes[0]])
        self.assertEqual(diagnostics['d6_retry_count'],1)

    def test_partial_batch_below_coverage_cannot_be_reported_complete(self):
        capture=BatchCapture({},NOW.timestamp(),{})
        with self.assertRaises(BatchFallback):verify_batch(capture,['600000.SH'],{},None,NOW,True,clock=lambda:NOW)
