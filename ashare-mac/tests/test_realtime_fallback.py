import unittest
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pandas as pd

from engine.intraday import normalize_quote
from engine.intraday_runner import IntradayProvider


NOW = datetime(2026, 9, 7, 14, 45, tzinfo=ZoneInfo('Asia/Shanghai'))


def quote(code, close=10.4, trade_time='20260907144500', updated_at='2026-09-07 14:45:00'):
    return dict(ts_code=code, name='测试股票', pre_close=10., open=close, high=close,
                low=close, close=close, vol=100., amount=close * 100,
                trade_time=trade_time, updated_at=updated_at)


class FakeProvider(IntradayProvider):
    def __init__(self, rows):
        self.rows = rows
        self.requests = []

    def get(self, api, **params):
        self.assert_rt_k(api)
        self.requests.append(dict(params))
        requested = params['ts_code'].split(',')
        return pd.DataFrame([self.rows[code] for code in requested if code in self.rows])

    @staticmethod
    def assert_rt_k(api):
        if api != 'rt_k':
            raise AssertionError('unexpected API in quote fixture: ' + api)


class RealtimeFallbackTests(unittest.TestCase):
    def test_large_universe_uses_explicit_batches_of_at_most_two_hundred_and_requests_updated_at(self):
        codes = [f'{index:06d}.SZ' for index in range(1001)]
        provider = FakeProvider({code: quote(code) for code in codes})
        with patch('engine.intraday_runner.local_now', return_value=NOW), \
             patch('engine.intraday_runner.sina_quotes', return_value=[], create=True) as fallback:
            rows = provider.quotes(codes)

        batches = [request['ts_code'].split(',') for request in provider.requests]
        self.assertEqual(len(rows), len(codes))
        self.assertEqual({row['ts_code'] for row in rows}, set(codes))
        # Concurrent requests may start in a different order; their chunks must be exact.
        self.assertCountEqual(batches,[codes[i:i+200] for i in range(0,len(codes),200)])
        self.assertTrue(all(1 <= len(batch) <= 200 for batch in batches))
        self.assertTrue(all('*' not in request['ts_code'] for request in provider.requests))
        self.assertTrue(all('updated_at' in request['fields'].split(',') for request in provider.requests))
        fallback.assert_not_called()

    def test_fresh_promax_timestamp_does_not_call_fallback(self):
        code = '600000.SH'
        provider = FakeProvider({code: quote(code, close=10.4)})
        with patch('engine.intraday_runner.local_now', return_value=NOW), \
             patch('engine.intraday_runner.sina_quotes', create=True) as fallback:
            rows = provider.quotes([code])

        self.assertEqual(len(rows), 1)
        self.assertEqual(normalize_quote(rows[0], NOW)['close'], 10.4)
        fallback.assert_not_called()

    def test_missing_promax_time_replaces_the_entire_row_with_a_fresh_fallback_snapshot(self):
        code = '600000.SH'
        primary = quote(code, close=10.4, trade_time='20260907', updated_at=None)
        replacement = quote(code, close=20., trade_time='20260907144500', updated_at=None)
        provider = FakeProvider({code: primary})
        with patch('engine.intraday_runner.local_now', return_value=NOW), \
             patch('engine.intraday_runner.sina_quotes', return_value=[replacement], create=True) as fallback:
            rows = provider.quotes([code])

        fallback.assert_called_once_with([code])
        self.assertEqual(len(rows), 1)
        normalized = normalize_quote(rows[0], NOW)
        self.assertEqual(normalized['close'], 20.)
        self.assertEqual(normalized['amount'], 2000.)
        self.assertEqual(normalized['time_basis'], 'trade_time')

    def test_stale_primary_uses_only_requested_rows_from_the_fresh_fallback_snapshot(self):
        requested = '600000.SH'
        unrequested = '600999.SH'
        provider = FakeProvider({requested: quote(requested, close=10.4, trade_time='20260907144000')})
        fallback_rows = [quote(requested, close=20.), quote(unrequested, close=99.)]
        with patch('engine.intraday_runner.local_now', return_value=NOW), \
             patch('engine.intraday_runner.sina_quotes', return_value=fallback_rows, create=True) as fallback:
            rows = provider.quotes([requested])

        fallback.assert_called_once_with([requested])
        self.assertEqual([row['ts_code'] for row in rows], [requested])
        self.assertEqual(normalize_quote(rows[0], NOW)['close'], 20.)

    def test_fallback_without_a_fresh_time_never_becomes_a_valid_quote(self):
        code = '600000.SH'
        for label, replacement in [
            ('missing', quote(code, close=20., trade_time='20260907', updated_at=None)),
            ('stale', quote(code, close=20., trade_time='20260907144000', updated_at=None)),
        ]:
            with self.subTest(label=label):
                primary = quote(code, close=10.4, trade_time='20260907', updated_at=None)
                provider = FakeProvider({code: primary})
                with patch('engine.intraday_runner.local_now', return_value=NOW), \
                     patch('engine.intraday_runner.sina_quotes', return_value=[replacement], create=True) as fallback:
                    rows = provider.quotes([code])

                fallback.assert_called_once_with([code])
                valid = []
                for row in rows:
                    try:
                        valid.append(normalize_quote(row, NOW))
                    except (TypeError, ValueError):
                        pass
                self.assertEqual(valid, [])


if __name__ == '__main__':
    unittest.main()
