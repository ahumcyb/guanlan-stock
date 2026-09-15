import json
import os
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from engine.datta import DattaError
from engine.market_config import market_configuration, market_provider_name
from engine.market_source import DattaMarketProvider, make_daily_provider
from engine.datta import decode_quote
from tests.test_datta import quote_payload, NOW


class MarketSourceTests(unittest.TestCase):
    def test_batch_policy_distinguishes_the_mac_primary_from_server_fallback(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'source.json'
            with patch.dict(os.environ,{'GUANLAN_MARKET_CONFIG':str(path),'GUANLAN_MARKET_PROVIDER':''}):
                path.write_text(json.dumps(dict(provider='datta',quote_mode='d101_batch')))
                self.assertEqual(market_provider_name(),'达塔批量初筛＋D6复核')
                path.write_text(json.dumps(dict(provider='promax',primary_provider='datta',primary_quote_mode='d101_batch')))
                with self.assertRaises(DattaError):market_provider_name()
                path.write_text(json.dumps(dict(provider='datta',quote_mode='unverified')))
                with self.assertRaises(DattaError):market_configuration()

    def test_rejected_batch_retries_the_complete_d6_universe(self):
        from engine.d101_batch import BatchFallback
        from unittest.mock import Mock
        client=Mock();client.quotes.return_value=[decode_quote(quote_payload(),'600000.SH')]
        client.diagnostics=dict(provider='datta_d6')
        with patch.dict(os.environ,{'GUANLAN_MARKET_PROVIDER':'datta'}),\
             patch('engine.market_source.local_now',return_value=NOW),\
             patch('engine.market_source.capture_batch',side_effect=BatchFallback('wrong_trade_date')),\
             patch('engine.datta_session.require_session'):
            provider=DattaMarketProvider(client=client)
            result=provider.screen_quotes({'600000.SH':{},'600001.SH':{}},True)
        client.quotes.assert_called_once_with(['600000.SH','600001.SH'])
        self.assertEqual(len(result),1)
        self.assertEqual(provider.quote_diagnostics['mode'],'d6_fallback')
        self.assertEqual(provider.quote_diagnostics['batch_fallback_reason'],'wrong_trade_date')

    def test_explicit_source_config_and_invalid_config_are_not_silent_fallbacks(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'source.json'
            with patch.dict(os.environ,{'GUANLAN_MARKET_CONFIG':str(path),'GUANLAN_MARKET_PROVIDER':''}):
                with self.assertRaises(DattaError):market_configuration()
                path.write_text(json.dumps(dict(provider='promax')))
                with self.assertRaises(DattaError):market_configuration()
                path.write_text(json.dumps(dict(provider='datta',workers=24)))
                self.assertEqual(market_configuration()['provider'],'datta')
                path.write_text(json.dumps(dict(provider='datta',base_url='http://remote.example:8080')))
                with self.assertRaises(DattaError):market_configuration()

    def test_no_reference_api_can_fall_back_to_retired_provider(self):
        def forbidden():raise AssertionError('Retired provider was constructed')
        with patch.dict(os.environ,{'GUANLAN_MARKET_PROVIDER':'datta'}):
            provider=DattaMarketProvider(forbidden)
            for api in ['adj_factor','stk_limit','daily_basic','trade_cal']:
                with self.assertRaises(DattaError):provider.get(api,trade_date='20260915')
            self.assertIsInstance(make_daily_provider(forbidden),DattaMarketProvider)

    def test_legacy_configuration_and_constructor_are_disabled(self):
        from engine.provider import ProMax
        with self.assertRaises(ValueError):ProMax()
        with patch.dict(os.environ,{'GUANLAN_MARKET_PROVIDER':'promax'}):
            with self.assertRaises(DattaError):make_daily_provider()

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
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'GUANLAN_MARKET_PROVIDER':'datta'}),\
             patch('engine.market_source.local_now',return_value=NOW),\
             patch('engine.intraday_runner.local_now',return_value=NOW),\
             patch('engine.intraday_runner.features_for',return_value=features):
            provider=DattaMarketProvider(no_reference,Client());provider.batch_enabled=False
            report=run(Path(directory),Path(directory)/'cache',provider=provider,slot_id='20260908-1430')
        self.assertEqual(report['status'],'ready')
        self.assertEqual(report['fresh_count'],1)
        self.assertEqual(report['bottom_volume']['matched_count'],1)
        self.assertEqual(report['quote_diagnostics']['provider'],'datta_d6')
        self.assertTrue(any('达塔 D6' in text for text in report['warnings']))
