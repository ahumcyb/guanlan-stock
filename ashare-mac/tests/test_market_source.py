import json
import os
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from engine.datta import DattaError
from engine.market_config import market_configuration
from engine.market_source import DattaMarketProvider, make_daily_provider
from engine.datta import decode_quote
from tests.test_datta import quote_payload, NOW


class MarketSourceTests(unittest.TestCase):
    def test_explicit_source_config_and_invalid_config_are_not_silent_fallbacks(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'source.json'
            with patch.dict(os.environ,{'GUANLAN_MARKET_CONFIG':str(path),'GUANLAN_MARKET_PROVIDER':''}):
                with self.assertRaises(DattaError):market_configuration()
                path.write_text(json.dumps(dict(provider='promax')))
                self.assertEqual(market_configuration()['provider'],'promax')
                path.write_text(json.dumps(dict(provider='datta',workers=24)))
                self.assertEqual(market_configuration()['provider'],'datta')
                path.write_text(json.dumps(dict(provider='datta',base_url='http://remote.example:8080')))
                with self.assertRaises(DattaError):market_configuration()

    def test_reference_fallback_never_fetches_stock_prices(self):
        calls=[]
        class Reference:
            def fetch(self,api,**params):
                calls.append(api)
                if api=='stock_basic':return pd.DataFrame(dict(ts_code=['600000.SH','920000.BJ']))
                if api=='daily':raise AssertionError('Prices came from the old source')
                return pd.DataFrame(dict(adj_factor=[1.]))
        class Client:
            def collect(self,codes,fetch,budget):return [row for code in codes for row in fetch(code)]
            def history(self,code,period,start,end):
                return [dict(ts_code=code,trade_date=start,open=9.21,high=9.34,low=9.21,close=9.28,
                             pre_close=9.23,vol=403779.31,amount=374763.157)]
        with patch.dict(os.environ,{'GUANLAN_MARKET_PROVIDER':'promax'}):
            provider=DattaMarketProvider(Reference,Client())
            provider.prepare_days(['20260908'])
            result=provider.fetch('daily',trade_date='20260908')
            self.assertEqual(set(result.ts_code),{'600000.SH','920000.BJ'})
            self.assertEqual(len(provider.fetch('stock_basic',list_status='L')),2)
            provider.fetch('adj_factor',trade_date='20260908')
        self.assertEqual(calls,['stock_basic','adj_factor'])

    def test_legacy_factory_remains_explicitly_selectable(self):
        reference=object()
        with patch.dict(os.environ,{'GUANLAN_MARKET_PROVIDER':'promax'}):
            self.assertIs(make_daily_provider(lambda:reference),reference)

    def test_datta_quote_path_reaches_1430_screen_without_old_price_calls(self):
        from engine.intraday_runner import run
        class Client:
            diagnostics=dict(provider='datta_d6',requested=1,unavailable=0,elapsed_seconds=.01)
            def quotes(self,codes):return [decode_quote(quote_payload(),'600000.SH')]
            def quote(self,code):
                row=decode_quote(quote_payload(),'600000.SH');row['ts_code']=code;return row
        def no_reference():raise AssertionError('Cached realtime selection requested old provider prices')
        features=dict(previous='20260907',source_version='test',open_dates=['20260907','20260908'],warnings=[],
            features={'600000.SH':dict(name='浦发银行',date='20260907',observations=60,adjusted=True,
                                      last_close=9.23,low60=8.5,mean_volume5=10000000.)})
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'GUANLAN_MARKET_PROVIDER':'promax'}),\
             patch('engine.market_source.local_now',return_value=NOW),\
             patch('engine.intraday_runner.local_now',return_value=NOW),\
             patch('engine.intraday_runner.features_for',return_value=features):
            provider=DattaMarketProvider(no_reference,Client())
            report=run(Path(directory),Path(directory)/'cache',provider=provider,slot_id='20260908-1430')
        self.assertEqual(report['status'],'ready')
        self.assertEqual(report['fresh_count'],1)
        self.assertEqual(report['bottom_volume']['matched_count'],1)
        self.assertEqual(report['quote_diagnostics']['provider'],'datta_d6')
        self.assertTrue(any('达塔 D6' in text for text in report['warnings']))
