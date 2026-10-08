import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch

from engine.market_config import market_configuration,market_provider_name
from engine.market_source import DattaMarketProvider
from tests.test_datta import quote_payload,NOW
from engine.datta import decode_quote,DattaUnavailable

class D20xIntegrationTests(unittest.TestCase):
    def test_new_mode_is_explicit_and_displayed(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'market.json';path.write_text(json.dumps(dict(quote_mode='d101_d204')))
            with patch.dict(os.environ,{'GUANLAN_MARKET_CONFIG':str(path),'GUANLAN_MARKET_PROVIDER':''}):
                self.assertEqual(market_configuration()['quote_mode'],'d101_d204')
                self.assertIn('D204',market_provider_name())
                self.assertIn('D203',market_provider_name())

    def test_exhausted_points_do_not_trigger_expensive_full_universe_retry(self):
        settings=dict(base_url='http://127.0.0.1:8080',workers=24,quote_mode='d101_d204')
        d204=Mock()
        with patch('engine.market_source.market_configuration',return_value=settings),\
             patch('engine.market_source.capture_batch'),patch('engine.datta_session.require_session'),\
             patch('engine.market_source.verify_batch',side_effect=DattaUnavailable('积分不足')):
            provider=DattaMarketProvider(quote_client=d204)
            with self.assertRaises(DattaUnavailable):provider.screen_quotes({'600000.SH':{}},False)
        d204.quotes.assert_not_called()

    def test_new_quote_channel_reaches_existing_1430_screen(self):
        from engine.intraday_runner import run
        class Client:
            diagnostics=dict(provider='datta_d204',requested=1,unavailable=0,payload_bytes=100)
            def quotes(self,codes):return [decode_quote(quote_payload(),'600000.SH')]
            def quote(self,code):
                row=decode_quote(quote_payload(),'600000.SH');row.update(ts_code=code,quote_source='datta_d204');return row
        features=dict(previous='20260907',source_version='test',open_dates=['20260907','20260908'],warnings=[],
            features={'600000.SH':dict(name='浦发银行',date='20260907',observations=60,adjusted=True,
                                      last_close=9.23,low60=8.5,mean_volume5=10000000.)})
        settings=dict(base_url='http://127.0.0.1:8080',workers=24,quote_mode='d101_d204')
        with tempfile.TemporaryDirectory() as directory,\
             patch('engine.market_source.market_configuration',return_value=settings),\
             patch('engine.market_source.local_now',return_value=NOW),\
             patch('engine.intraday_runner.local_now',return_value=NOW),\
             patch('engine.intraday_runner.features_for',return_value=features):
            provider=DattaMarketProvider(client=Client(),quote_client=Client());provider.batch_enabled=False
            provider.enrich_candidates=lambda report:None
            report=run(Path(directory),Path(directory)/'cache',provider=provider,slot_id='20260908-1430')
        self.assertEqual(report['status'],'ready')
        self.assertEqual(report['bottom_volume']['matched_count'],1)
        self.assertEqual(report['quote_diagnostics']['provider'],'datta_d204')
        self.assertTrue(any('D204' in text for text in report['warnings']))
