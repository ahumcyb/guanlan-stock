import tempfile
import unittest
from pathlib import Path
import pandas as pd

from engine.data import validate, combine, publish_day
from engine.provider import parse_response


def daily():
    return pd.DataFrame([dict(ts_code='000001.SZ', trade_date='20260904',
                             open=10, high=11, low=9, close=10.5,
                             pre_close=10, vol=1000, amount=10000)])


class DataTests(unittest.TestCase):
    def test_duplicate_prices_rejected(self):
        with self.assertRaises(ValueError):
            validate(pd.concat([daily(), daily()]), 'daily')

    def test_impossible_candle_rejected(self):
        x = daily(); x.loc[0, 'high'] = 9
        with self.assertRaises(ValueError):
            validate(x, 'daily')

    def test_malformed_day_rejected(self):
        x = daily(); x.loc[0, 'trade_date'] = '20260230'
        with self.assertRaises(ValueError):
            validate(x, 'daily')

    def test_identical_overlap_deduplicates(self):
        self.assertEqual(len(combine([daily(), daily()], 'daily')), 1)

    def test_conflicting_overlap_rejected(self):
        x = daily(); x.loc[0, 'close'] = 10.6
        with self.assertRaises(ValueError):
            combine([daily(), x], 'daily')

    def test_failed_publication_keeps_previous_day(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            adj = daily()[['ts_code', 'trade_date']].assign(adj_factor=1.)
            lim = daily()[['ts_code', 'trade_date']].assign(up_limit=11., down_limit=9.)
            publish_day(root, '20260904', {'daily': daily(), 'adj_factor': adj, 'stk_limit': lim})
            before = (root/'20260904'/'daily.parquet').read_bytes()
            with self.assertRaises(ValueError):
                publish_day(root, '20260904', {'daily': daily(), 'adj_factor': adj.iloc[:0], 'stk_limit': lim})
            self.assertEqual(before, (root/'20260904'/'daily.parquet').read_bytes())

    def test_truncated_api_result_rejected(self):
        with self.assertRaises(ValueError):
            parse_response({'code': 0, 'count': 2, 'data': {'fields': ['a'], 'items': [[1]]}})

    def test_provider_errors_do_not_echo_payload(self):
        with self.assertRaisesRegex(ValueError, '^ProMax 返回错误状态$'):
            parse_response({'code': 401, 'msg': 'secret-should-never-be-echoed'})


if __name__ == '__main__':
    unittest.main()
