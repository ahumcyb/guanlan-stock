import unittest
import pandas as pd
from engine.datta_reference import continuous_factors, decode_universe
from engine.datta import DattaError


class DattaReferenceTests(unittest.TestCase):
    def test_cash_distribution_is_chained_from_actual_preclose(self):
        daily=pd.DataFrame([dict(ts_code='600000.SH',trade_date='20260915',close=9.2,pre_close=9.)])
        prior=pd.DataFrame([dict(ts_code='600000.SH',trade_date='20260914',close=10.)])
        factors=pd.DataFrame([dict(ts_code='600000.SH',trade_date='20260914',adj_factor=2.)])
        value=continuous_factors(daily,prior,factors,{'600000.SH':'19991110'})
        self.assertAlmostEqual(value.iloc[0].adj_factor,2*10/9)

    def test_missing_anchor_is_not_fabricated(self):
        day=pd.DataFrame([dict(ts_code='600000.SH',trade_date='20260915',close=9.2,pre_close=9.)])
        with self.assertRaises(DattaError):continuous_factors(day,day.iloc[:0],pd.DataFrame(),{'600000.SH':'19991110'})

    def test_bse_protocol_prefix_does_not_change_exchange(self):
        rows=[dict(code='SZ920001',name='例子',list_date=20200101,industry_name='制造')]
        self.assertEqual(decode_universe(rows,{'920001'}).iloc[0].ts_code,'920001.BJ')

    def test_duplicate_universe_rejected(self):
        row=dict(code='SZ000001',name='例子',list_date=19910403,industry_name='银行')
        with self.assertRaises(DattaError):decode_universe([row,row],set())

    def test_zero_limits_require_a_verified_ipo_window(self):
        from engine.datta_reference import no_limit_ipo,reference_quote
        from tests.test_datta import quote_payload
        days={'20260908','20260909','20260910','20260911','20260914','20260915'}
        self.assertTrue(no_limit_ipo('300001.SZ','20260914','20260908',days))
        self.assertFalse(no_limit_ipo('300001.SZ','20260915','20260908',days))
        self.assertFalse(no_limit_ipo('920001.BJ','20260909','20260908',days))
        self.assertTrue(no_limit_ipo('920001.BJ','20260908','20260908',days))
        self.assertFalse(no_limit_ipo('600000.SH','20260908','19991110',days))
        payload=quote_payload(upPx=0,downPx=0,circulationValue=33305838300*9.28)
        with self.assertRaises(DattaError):reference_quote(payload,'600000.SH')
        self.assertEqual(reference_quote(payload,'600000.SH',allow_no_limit=True)['up_limit'],0)

    def test_new_listing_bootstraps_observed_bars_before_target_day(self):
        from unittest.mock import patch
        from engine.market_source import DattaMarketProvider
        from tests.test_datta import quote_payload
        calls=[]
        class Client:
            def collect(self,codes,fetch,budget):
                result=[]
                for code in codes:
                    value=fetch(code);result.extend(value if isinstance(value,list) else [value])
                return result
            def history(self,code,period,start,end):
                calls.append((start,end))
                return [dict(ts_code=code,trade_date=day,open=9.2,high=9.4,low=9.1,close=9.28,
                             pre_close=9.23,vol=100.,amount=928.) for day in ['20260908','20260909']]
            def transport(self,path,params):
                return quote_payload(upPx=10000,downPx=8000,circulationValue=33305838300*9.28)
        basic=pd.DataFrame([dict(ts_code='600000.SH',name='例子',industry='行业',list_date='20260908')])
        with patch('engine.datta_reference.universe',return_value=basic):
            provider=DattaMarketProvider(client=Client())
            provider.set_history({'daily':pd.DataFrame(columns=['ts_code','trade_date','close']),
                                  'adj_factor':pd.DataFrame(columns=['ts_code','trade_date','adj_factor'])})
            provider.prepare_days(['20260909'])
            self.assertEqual(calls,[('20260908','20260909')])
            self.assertEqual(len(provider.fetch('adj_factor',trade_date='20260909')),1)

    def test_transient_per_stock_error_is_retried_without_another_provider(self):
        from engine.datta import DattaClient
        attempts=[]
        def fetch(code):
            attempts.append(code)
            if len(attempts)==1:raise DattaError('temporary local transport failure')
            return {'ts_code':code}
        client=DattaClient(transport=lambda *args:None)
        self.assertEqual(client.collect(['000001.SZ'],fetch),[{'ts_code':'000001.SZ'}])
        self.assertEqual(client.diagnostics['unavailable'],0)

    def test_control_transport_grace_never_extends_or_revives_expired_receipts(self):
        from mobile_server.datta_supervisor import transport_grace
        from mobile_server.mac_worker import WorkerRequestError,LostLease
        self.assertTrue(transport_grace(TimeoutError(),'poll',145,True,120))
        self.assertTrue(transport_grace(WorkerRequestError(503),'activate',145,True,120))
        self.assertFalse(transport_grace(TimeoutError(),'poll',145,True,136))
        self.assertFalse(transport_grace(TimeoutError(),'poll',145,False,120))
        self.assertFalse(transport_grace(OSError(),'receipt',145,True,120))
        self.assertFalse(transport_grace(LostLease(),'poll',145,True,120))
        self.assertFalse(transport_grace(WorkerRequestError(401),'poll',145,True,120))
