import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

import pandas as pd

from engine.data import publish_day
from engine.market_source import DattaMarketProvider
from engine.provider import PAGE_SIZE, ProMax, ProMaxRowLimit, ProMaxUnavailable
from engine.update import update
from tests.test_data import daily


DATE = '20260911'


def codes(count):
    return [f'{index:06d}.SZ' for index in range(count)]


def factors(requested, date=DATE):
    return pd.DataFrame({
        'ts_code': list(requested),
        'trade_date': [date] * len(requested),
        'adj_factor': [1.0] * len(requested),
    })


def row_limit():
    return ProMaxRowLimit('row_count_exceeds_limit')


class BatchedFactors(ProMax):
    def __init__(self, known, mutate=None, fail_batch=None):
        self.calls = []
        self.mutate = mutate
        self.fail_batch = fail_batch
        self.set_known_codes(known)

    def _page(self, api, params):
        self.calls.append((api, dict(params)))
        self.assert_common(api, params)
        if 'ts_code' not in params:
            raise AssertionError('Known single-day factors must not try the oversized full query')
        batch = params['ts_code'].split(',')
        if self.fail_batch is not None and len(self.calls) - 1 == self.fail_batch:
            raise ValueError('one factor batch failed')
        frame = factors(batch)
        return self.mutate(frame, batch) if self.mutate else frame

    @staticmethod
    def assert_common(api, params):
        if api != 'adj_factor' or params.get('trade_date') != DATE or params.get('limit') != 1000:
            raise AssertionError((api, params))


class ProMaxRecoveryTests(unittest.TestCase):
    def test_exhausted_503_retries_the_same_factor_codes_with_an_equivalent_date_range(self):
        requested = ['603322.SH', '603325.SH']

        class RangeFallback(ProMax):
            def __init__(self):
                self.calls = []

            def _page(self, api, params):
                self.calls.append((api, dict(params)))
                if 'trade_date' in params:
                    raise ProMaxUnavailable('safe unavailable')
                self_test.assertEqual(set(params), {'ts_code', 'start_date', 'end_date', 'limit'})
                self_test.assertEqual(params['start_date'], DATE)
                self_test.assertEqual(params['end_date'], DATE)
                self_test.assertEqual(params['ts_code'], ','.join(requested))
                self_test.assertEqual(params['limit'], 1000)
                return factors(requested)

        self_test = self
        client = RangeFallback()
        result = client.fetch_factors(DATE, requested)

        self.assertEqual(set(result.ts_code), set(requested))
        self.assertEqual(len(client.calls), 2)

    def test_equivalent_factor_range_still_rejects_wrong_dates_and_double_failure(self):
        class RangeFallback(ProMax):
            def __init__(self, interval_result):
                self.calls = []
                self.interval_result = interval_result

            def _page(self, api, params):
                self.calls.append(dict(params))
                if 'trade_date' in params:
                    raise ProMaxUnavailable('safe unavailable')
                if isinstance(self.interval_result, Exception):
                    raise self.interval_result
                return self.interval_result

        wrong = RangeFallback(factors(['603322.SH'], '20260910'))
        with self.assertRaises(ValueError):
            wrong.fetch_factors(DATE, ['603322.SH'])
        self.assertEqual(len(wrong.calls), 2)

        failed = RangeFallback(ProMaxUnavailable('range unavailable'))
        with self.assertRaises(ProMaxUnavailable):
            failed.fetch_factors(DATE, ['603322.SH'])
        self.assertEqual(len(failed.calls), 2)

    def test_auth_or_other_errors_never_switch_factor_query_shape(self):
        class Unauthorized(ProMax):
            def __init__(self):
                self.calls = []

            def _page(self, api, params):
                self.calls.append(dict(params))
                raise ValueError('ProMax HTTP 401')

        client = Unauthorized()
        with self.assertRaises(ValueError):
            client.fetch_factors(DATE, ['603322.SH'])
        self.assertEqual(len(client.calls), 1)
        self.assertIn('trade_date', client.calls[0])
        self.assertNotIn('start_date', client.calls[0])

    def test_retry_after_on_429_is_honored_but_ordinary_400_and_401_are_not_retried(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self, limit):
                return b'{"code":0,"count":0,"data":{"fields":[],"items":[]}}'

        waited = [0.0]

        class RateLimitedThenReady:
            calls = 0

            def open(self, *args, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    raise HTTPError('https://provider.invalid', 429, 'rate limited',
                                    {'Retry-After': '7'}, io.BytesIO(b'{}'))
                self_test.assertGreaterEqual(waited[0], 7.0)
                return Response()

        self_test = self
        opener = RateLimitedThenReady()
        client = object.__new__(ProMax)
        client._secret = 'unit-test-secret'
        with patch.object(ProMax, '_throttle', return_value=None), \
             patch('engine.provider.build_opener', return_value=opener), \
             patch('engine.provider.time.sleep', side_effect=lambda seconds: waited.__setitem__(0, waited[0] + seconds)):
            self.assertTrue(client._page('adj_factor', {'trade_date': DATE}).empty)
        self.assertEqual(opener.calls, 2)

        class LongRetryAfter:
            calls = 0

            def open(self, *args, **kwargs):
                self.calls += 1
                raise HTTPError('https://provider.invalid', 429, 'rate limited',
                                {'Retry-After': '61'}, io.BytesIO(b'{}'))

        long_wait = LongRetryAfter()
        with patch.object(ProMax, '_throttle', return_value=None), \
             patch('engine.provider.build_opener', return_value=long_wait), \
             patch('engine.provider.time.sleep') as sleep:
            with self.assertRaisesRegex(ValueError, '较长等待'):
                client._page('adj_factor', {'trade_date': DATE})
            self.assertEqual(long_wait.calls, 1)
            sleep.assert_not_called()

        for status in [400, 401]:
            class RejectingOpener:
                calls = 0

                def open(self, *args, **kwargs):
                    self.calls += 1
                    raise HTTPError('https://provider.invalid', status, 'rejected', {},
                                    io.BytesIO(b'{"message":"invalid request"}'))

            rejected = RejectingOpener()
            with self.subTest(status=status), \
                 patch.object(ProMax, '_throttle', return_value=None), \
                 patch('engine.provider.build_opener', return_value=rejected), \
                 patch('engine.provider.time.sleep') as sleep:
                with self.assertRaises(ValueError):
                    client._page('adj_factor', {'trade_date': DATE})
                self.assertEqual(rejected.calls, 1)
                sleep.assert_not_called()

    def test_request_throttle_is_shared_by_independent_clients(self):
        import engine.provider as provider_module

        clock = [100.0]
        starts = []

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self, limit):
                return b'{"code":0,"count":0,"data":{"fields":[],"items":[]}}'

        class Opener:
            def open(self, *args, **kwargs):
                starts.append(clock[0])
                return Response()

        first = object.__new__(ProMax)
        second = object.__new__(ProMax)
        first._secret = second._secret = 'unit-test-secret'
        with patch.object(provider_module, '_NEXT_REQUEST_AT', 0.0), \
             patch('engine.provider.time.monotonic', side_effect=lambda: clock[0]), \
             patch('engine.provider.time.sleep', side_effect=lambda seconds: clock.__setitem__(0, clock[0] + seconds)), \
             patch('engine.provider.build_opener', return_value=Opener()):
            first._page('adj_factor', {'trade_date': '20260910'})
            second._page('adj_factor', {'trade_date': DATE})

        self.assertEqual(len(starts), 2)
        self.assertGreaterEqual(starts[1] - starts[0], 2.1 - 1e-9)

    def test_explicit_factor_codes_are_per_call_and_do_not_mutate_shared_known_codes(self):
        class Factors(ProMax):
            def __init__(self):
                self.calls = []
                self.set_known_codes(['999999.SZ'])

            def _page(self, api, params):
                self.calls.append((api, dict(params)))
                requested = params['ts_code'].split(',')
                return factors(requested, params['trade_date'])

        client = Factors()
        first = ['000001.SZ', '000002.SZ']
        second = ['600001.SH']

        one = client.fetch_factors('20260910', first)
        two = client.fetch_factors(DATE, second)

        self.assertEqual(set(one.ts_code), set(first))
        self.assertEqual(set(two.ts_code), set(second))
        self.assertEqual([call[1]['ts_code'] for call in client.calls],
                         [','.join(first), ','.join(second)])
        self.assertTrue(all(call[1]['limit'] == 1000 for call in client.calls))
        self.assertTrue(all('999999.SZ' not in call[1]['ts_code'] for call in client.calls))
        self.assertEqual(client._known_codes, ('999999.SZ',))

    def test_only_known_row_limit_http_400_gets_the_safe_exception_type(self):
        def opener(status, message):
            body = io.BytesIO(json.dumps({'message': message}).encode())
            error = HTTPError('https://provider.invalid', status, message, {}, body)

            class RejectingOpener:
                def open(self, *args, **kwargs):
                    raise error

            return RejectingOpener()

        client = object.__new__(ProMax)
        client._secret = 'unit-test-secret'
        with patch.object(ProMax, '_throttle', return_value=None), \
             patch('engine.provider.build_opener', return_value=opener(400, 'row count exceeds limit')):
            with self.assertRaises(ProMaxRowLimit):
                client._page('adj_factor', {'trade_date': DATE, 'limit': PAGE_SIZE})
        for status, message in [(400, 'invalid query'), (400, 'permission denied'), (401, 'unauthorized')]:
            with self.subTest(status=status, message=message), \
                 patch.object(ProMax, '_throttle', return_value=None), \
                 patch('engine.provider.build_opener', return_value=opener(status, message)):
                with self.assertRaises(ValueError) as error:
                    client._page('adj_factor', {'trade_date': DATE, 'limit': PAGE_SIZE})
                self.assertNotIsInstance(error.exception, ProMaxRowLimit)

    def test_single_day_factors_retry_all_known_codes_in_batches_of_at_most_one_hundred(self):
        known = codes(205)
        client = BatchedFactors(known)

        result = client.fetch('adj_factor', trade_date=DATE)

        self.assertEqual(PAGE_SIZE, 5000)
        self.assertEqual(set(result.ts_code), set(known))
        self.assertEqual(set(result.trade_date), {DATE})
        batches = [params['ts_code'].split(',') for _, params in client.calls]
        self.assertEqual([len(batch) for batch in batches], [100, 100, 5])
        self.assertEqual([code for batch in batches for code in batch], sorted(known))

    def test_factor_batch_returning_a_full_thousand_rows_is_rejected_before_deduplication(self):
        def full_page(frame, batch):
            return pd.concat([frame.iloc[[0]]] * 1000, ignore_index=True)

        client = BatchedFactors(['000001.SZ'], full_page)
        with self.assertRaisesRegex(ValueError, '截断'):
            client.fetch_factors(DATE, ['000001.SZ'])
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(client.calls[0][1]['limit'], 1000)

    def test_batch_response_cannot_escape_requested_codes_change_date_or_conflict(self):
        def outside(frame, batch):
            return pd.concat([frame, factors(['999999.SZ'])], ignore_index=True)

        def wrong_date(frame, batch):
            frame.loc[0, 'trade_date'] = '20260910'
            return frame

        def conflict(frame, batch):
            duplicate = frame.iloc[[0]].copy()
            duplicate['adj_factor'] = 2.0
            return pd.concat([frame, duplicate], ignore_index=True)

        for mutation in [outside, wrong_date, conflict]:
            with self.subTest(mutation=mutation.__name__), self.assertRaises(ValueError):
                BatchedFactors(codes(2), mutation).fetch('adj_factor', trade_date=DATE)

    def test_one_failed_batch_discards_the_whole_recovery(self):
        client = BatchedFactors(codes(101), fail_batch=1)
        with self.assertRaisesRegex(ValueError, 'batch failed'):
            client.fetch('adj_factor', trade_date=DATE)
        self.assertEqual(len(client.calls), 2)

    def test_missing_factor_rows_remain_missing_for_daily_integrity_check(self):
        def omit_last(frame, batch):
            return frame.iloc[:-1].copy()

        known = ['000001.SZ', '000002.SZ']
        result = BatchedFactors(known, omit_last).fetch('adj_factor', trade_date=DATE)
        self.assertEqual(set(result.ts_code), {'000001.SZ'})

        first = daily().copy()
        first['trade_date'] = DATE
        second = first.copy()
        second['ts_code'] = '000002.SZ'
        prices = pd.concat([first, second], ignore_index=True)
        limits = prices[['ts_code', 'trade_date']].assign(up_limit=11.0, down_limit=9.0)
        with tempfile.TemporaryDirectory() as folder, self.assertRaisesRegex(ValueError, 'adj_factor'):
            publish_day(Path(folder), DATE, {'daily': prices, 'adj_factor': result, 'stk_limit': limits})

    def test_batch_errors_fail_whole_factor_request_while_other_tables_never_use_code_batches(self):
        class Reject(ProMax):
            def __init__(self, error, known=True):
                self.error = error
                self.calls = []
                if known:
                    self.set_known_codes(codes(150))

            def _page(self, api, params):
                self.calls.append((api, dict(params)))
                raise self.error

        for message in ['authentication failed', 'arbitrary HTTP 400', 'HTTP 503 exhausted']:
            with self.subTest(message=message), self.assertRaises(ValueError):
                client = Reject(ValueError(message))
                client.fetch('adj_factor', trade_date=DATE)
            self.assertEqual(len(client.calls), 1)
            requested = client.calls[0][1]['ts_code'].split(',')
            self.assertLessEqual(len(requested), 100)

        client = Reject(ValueError('HTTP 503 exhausted'), known=False)
        with self.assertRaises(ValueError):
            client.fetch('adj_factor', trade_date=DATE)
        self.assertEqual(len(client.calls), 1)
        self.assertNotIn('ts_code', client.calls[0][1])

        for api, error in [('stk_limit', row_limit()), ('stock_basic', row_limit())]:
            with self.subTest(api=api), self.assertRaises(ValueError):
                client = Reject(error)
                params = {'trade_date': DATE} if api != 'stock_basic' else {'list_status': 'L'}
                client.fetch(api, **params)
            self.assertEqual(len(client.calls), 2 if api == 'stk_limit' else 1)
            self.assertTrue(all('ts_code' not in params for _, params in client.calls))

        class ConflictingBasic(ProMax):
            def __init__(self):
                self.set_known_codes(codes(2))

            def _page(self, api, params):
                return pd.DataFrame([
                    {'ts_code': '300001.SZ', 'name': '旧名称', 'industry': '行业甲'},
                    {'ts_code': '300001.SZ', 'name': '新名称', 'industry': '行业乙'},
                ])

        with self.assertRaisesRegex(ValueError, '冲突'):
            ConflictingBasic().fetch('stock_basic', list_status='L')

    def test_stk_limit_keeps_the_offset_when_a_later_page_must_shrink(self):
        first_codes = codes(5000)
        remaining_codes = [f'{index:06d}.SZ' for index in range(5000, 5641)]

        class Limits(ProMax):
            def __init__(self):
                self.calls = []

            def _page(self, api, params):
                self.calls.append(dict(params))
                if api != 'stk_limit' or 'ts_code' in params:
                    raise AssertionError((api, params))
                key = (params['offset'], params['limit'])
                if key == (0, 5000):
                    selected = first_codes
                elif key == (5000, 5000):
                    raise row_limit()
                elif key == (5000, 1000):
                    selected = remaining_codes
                else:
                    raise AssertionError(key)
                return pd.DataFrame({'ts_code': selected, 'trade_date': DATE,
                                     'up_limit': 11.0, 'down_limit': 9.0})

        client = Limits()
        result = client.fetch('stk_limit', trade_date=DATE)

        self.assertEqual(len(result), 5641)
        self.assertEqual(set(result.ts_code), set(first_codes + remaining_codes))
        self.assertEqual([(call['offset'], call['limit']) for call in client.calls],
                         [(0, 5000), (5000, 5000), (5000, 1000)])
        self.assertTrue(all('ts_code' not in call for call in client.calls))

    def test_update_supplies_all_source_daily_codes_before_reference_or_factor_fetches(self):
        known = codes(4001)
        keys = pd.DataFrame({'ts_code': known, 'trade_date': DATE})
        frames = {
            'daily': keys.assign(open=10.0, high=11.0, low=9.0, close=10.0,
                                 pre_close=10.0, vol=100.0, amount=100000.0),
            'adj_factor': keys.assign(adj_factor=1.0),
            'stk_limit': keys.assign(up_limit=11.0, down_limit=9.0),
        }

        class Provider:
            def __init__(self):
                self.known = None

            def set_known_codes(self, values):
                self.known = list(values)

            def fetch(self, api, **params):
                if api == 'trade_cal':
                    days = pd.date_range('20250101', '20261231').strftime('%Y%m%d')
                    table = pd.DataFrame({'exchange': 'SSE', 'cal_date': days,
                                          'is_open': [int(day == DATE) for day in days]})
                    return table[table.is_open == params['is_open']].reset_index(drop=True)
                if api == 'stock_basic':
                    return keys[['ts_code']].assign(name='测试', industry='行业', list_date='20000101')
                raise AssertionError(api)

        provider = Provider()
        with tempfile.TemporaryDirectory() as folder, \
             patch('engine.update.make_daily_provider', return_value=provider), \
             patch('engine.update.read_dataset', side_effect=lambda root, overlay, kind: frames[kind]):
            update(Path(folder) / 'source', Path(folder) / 'overlay', through=DATE)
        self.assertEqual(set(provider.known or []), set(known))

    def test_update_fetches_factors_for_the_downloaded_day_codes_not_historical_orphans(self):
        old_date = '20260910'
        today = codes(4001)
        orphan = '999999.SZ'
        historical = today + [orphan]
        old_keys = pd.DataFrame({'ts_code': historical, 'trade_date': old_date})
        datasets = {
            'daily': old_keys.assign(open=10.0, high=11.0, low=9.0, close=10.0,
                                     pre_close=10.0, vol=100.0, amount=100000.0),
            'adj_factor': old_keys.assign(adj_factor=1.0),
            'stk_limit': old_keys.assign(up_limit=11.0, down_limit=9.0),
        }
        today_keys = pd.DataFrame({'ts_code': today, 'trade_date': DATE})

        class Provider:
            reference_warning = None

            def __init__(self):
                self.shared = []
                self.factor_calls = []

            def set_known_codes(self, values):
                self.shared = list(values)

            def fetch_factors(self, date, requested):
                self.factor_calls.append((date, list(requested)))
                return factors(requested, date)

            def fetch(self, api, **params):
                if api == 'trade_cal':
                    days = pd.date_range('20250101', '20261231').strftime('%Y%m%d')
                    opened = {old_date, DATE}
                    table = pd.DataFrame({'exchange': 'SSE', 'cal_date': days,
                                          'is_open': [int(day in opened) for day in days]})
                    return table[table.is_open == params['is_open']].reset_index(drop=True)
                if api == 'daily':
                    return today_keys.assign(open=10.0, high=11.0, low=9.0, close=10.0,
                                             pre_close=10.0, vol=100.0, amount=100000.0)
                if api == 'stk_limit':
                    return today_keys.assign(up_limit=11.0, down_limit=9.0)
                if api == 'stock_basic':
                    return old_keys[['ts_code']].assign(name='测试', industry='行业', list_date='20000101')
                if api == 'adj_factor':
                    raise AssertionError('update bypassed fetch_factors')
                raise AssertionError(api)

        provider = Provider()
        with tempfile.TemporaryDirectory() as folder, \
             patch('engine.update.make_daily_provider', return_value=provider), \
             patch('engine.update.read_dataset', side_effect=lambda root, overlay, kind: datasets[kind]):
            result = update(Path(folder) / 'source', Path(folder) / 'overlay', through=DATE)

        self.assertEqual(result['updated_days'], 1)
        self.assertIn(orphan, provider.shared)
        self.assertEqual(len(provider.factor_calls), 1)
        self.assertEqual(provider.factor_calls[0][0], DATE)
        self.assertEqual(set(provider.factor_calls[0][1]), set(today))
        self.assertNotIn(orphan, provider.factor_calls[0][1])


# Mixed Datta/ProMax reference recovery was retired with the Datta-only migration.
# Replacement coverage is in test_datta_reference and test_market_source.
