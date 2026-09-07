import copy
import unittest

import pandas as pd

from mobile_server.daily_performance import evaluate_selections, previous_open_date


SIGNAL_DATE = '20260904'
EVALUATION_DATE = '20260907'
STRATEGIES = [
    ('leaders', '流动性趋势'),
    ('pullback', '缩量回踩转强'),
    ('golden_pit', '黄金坑'),
    ('momentum_60', '60 日风险调整动量'),
]


def saved_snapshot(picks_by_strategy):
    return {
        'date': SIGNAL_DATE,
        'generation': SIGNAL_DATE + 'T161100-abcdef',
        'data_revision': SIGNAL_DATE + '-' + 'a' * 16,
        'strategies': [
            {'id': strategy_id, 'name': name, 'picks': copy.deepcopy(picks_by_strategy.get(strategy_id, []))}
            for strategy_id, name in STRATEGIES
        ],
    }


def daily(date, prices):
    return pd.DataFrame([
        {'ts_code': code, 'trade_date': date, 'close': close}
        for code, close in prices.items()
    ])


def factors(date, values):
    return pd.DataFrame([
        {'ts_code': code, 'trade_date': date, 'adj_factor': factor}
        for code, factor in values.items()
    ])


def result_for(result, strategy_id):
    return next(row for row in result['strategies'] if row['id'] == strategy_id)


class DailySelectionPerformanceTests(unittest.TestCase):
    def test_only_previous_saved_picks_are_evaluated_not_new_daily_winners(self):
        snapshot = saved_snapshot({'leaders': [
            {'ts_code': '600000.SH', 'name': '昨日精选A', 'close': 10., 'rank': 1},
        ]})
        previous = daily(SIGNAL_DATE, {'600000.SH': 10., '600001.SH': 10.})
        current = daily(EVALUATION_DATE, {'600000.SH': 9., '600001.SH': 20.})
        previous_factor = factors(SIGNAL_DATE, {'600000.SH': 1., '600001.SH': 1.})
        current_factor = factors(EVALUATION_DATE, {'600000.SH': 1., '600001.SH': 1.})

        result = evaluate_selections(snapshot, previous, current, previous_factor,
                                     current_factor, EVALUATION_DATE)

        self.assertEqual(result['signal_date'], SIGNAL_DATE)
        self.assertEqual(result['evaluation_date'], EVALUATION_DATE)
        self.assertEqual(result['basis'], 'adjusted_close_to_close')
        leaders = result_for(result, 'leaders')
        self.assertEqual(leaders['status'], 'complete')
        self.assertEqual((leaders['selected_count'], leaders['settled_count']), (1, 1))
        self.assertEqual([row['ts_code'] for row in leaders['rows']], ['600000.SH'])
        self.assertNotIn('600001.SH', str(result))
        self.assertAlmostEqual(leaders['rows'][0]['return_pct'], -10.)
        self.assertAlmostEqual(leaders['mean_return_pct'], -10.)

    def test_adjusted_close_returns_handle_a_split_and_count_up_down_flat(self):
        snapshot = saved_snapshot({'golden_pit': [
            {'ts_code': '600000.SH', 'name': '拆股样本', 'close': 10., 'rank': 1},
            {'ts_code': '600001.SH', 'name': '下跌样本', 'close': 10., 'rank': 2},
            {'ts_code': '600002.SH', 'name': '平盘样本', 'close': 10., 'rank': 3},
        ]})
        previous = daily(SIGNAL_DATE, {'600000.SH': 10., '600001.SH': 10., '600002.SH': 10.})
        current = daily(EVALUATION_DATE, {'600000.SH': 5.2, '600001.SH': 9.8, '600002.SH': 10.})
        previous_factor = factors(SIGNAL_DATE, {'600000.SH': 1., '600001.SH': 1., '600002.SH': 1.})
        current_factor = factors(EVALUATION_DATE, {'600000.SH': 2., '600001.SH': 1., '600002.SH': 1.})

        result = evaluate_selections(snapshot, previous, current, previous_factor,
                                     current_factor, EVALUATION_DATE)
        group = result_for(result, 'golden_pit')

        self.assertEqual(group['status'], 'complete')
        self.assertEqual((group['selected_count'], group['settled_count']), (3, 3))
        self.assertEqual((group['up_count'], group['down_count'], group['flat_count']), (1, 1, 1))
        returns = {row['ts_code']: row['return_pct'] for row in group['rows']}
        self.assertAlmostEqual(returns['600000.SH'], 4.)
        self.assertAlmostEqual(returns['600001.SH'], -2.)
        self.assertAlmostEqual(returns['600002.SH'], 0.)
        self.assertAlmostEqual(group['mean_return_pct'], (4. - 2. + 0.) / 3)

    def test_missing_current_quote_or_either_factor_makes_mean_unknown_not_zero(self):
        picks = [
            {'ts_code': '600000.SH', 'name': '完整样本', 'close': 10., 'rank': 1},
            {'ts_code': '600001.SH', 'name': '缺今日行情', 'close': 10., 'rank': 2},
            {'ts_code': '600002.SH', 'name': '缺昨日因子', 'close': 10., 'rank': 3},
            {'ts_code': '600003.SH', 'name': '缺今日因子', 'close': 10., 'rank': 4},
        ]
        snapshot = saved_snapshot({'momentum_60': picks})
        previous = daily(SIGNAL_DATE, {code: 10. for code in ['600000.SH', '600001.SH', '600002.SH', '600003.SH']})
        current = daily(EVALUATION_DATE, {'600000.SH': 10.5, '600002.SH': 10.5, '600003.SH': 10.5})
        previous_factor = factors(SIGNAL_DATE, {'600000.SH': 1., '600001.SH': 1., '600003.SH': 1.})
        current_factor = factors(EVALUATION_DATE, {'600000.SH': 1., '600001.SH': 1., '600002.SH': 1.})

        result = evaluate_selections(snapshot, previous, current, previous_factor,
                                     current_factor, EVALUATION_DATE)
        group = result_for(result, 'momentum_60')

        self.assertEqual(group['status'], 'partial')
        self.assertEqual((group['selected_count'], group['settled_count']), (4, 1))
        self.assertEqual((group['up_count'], group['down_count'], group['flat_count']), (1, 0, 0))
        self.assertIsNone(group['mean_return_pct'])
        unresolved = [row for row in group['rows'] if row['status'] == 'unsettled']
        self.assertEqual({row['ts_code'] for row in unresolved}, {'600001.SH', '600002.SH', '600003.SH'})
        self.assertTrue(all(row['return_pct'] is None and row['reason'] for row in unresolved))

    def test_snapshot_close_mismatch_is_unsettled_instead_of_rebased(self):
        snapshot = saved_snapshot({'pullback': [
            {'ts_code': '600000.SH', 'name': '价格不一致', 'close': 10., 'rank': 1},
        ]})
        result = evaluate_selections(
            snapshot,
            daily(SIGNAL_DATE, {'600000.SH': 10.5}),
            daily(EVALUATION_DATE, {'600000.SH': 11.}),
            factors(SIGNAL_DATE, {'600000.SH': 1.}),
            factors(EVALUATION_DATE, {'600000.SH': 1.}),
            EVALUATION_DATE,
        )
        group = result_for(result, 'pullback')

        self.assertEqual(group['status'], 'partial')
        self.assertEqual(group['settled_count'], 0)
        self.assertIsNone(group['mean_return_pct'])
        self.assertEqual(group['rows'][0]['status'], 'unsettled')
        self.assertIsNone(group['rows'][0]['return_pct'])
        self.assertTrue(group['rows'][0]['reason'])

    def test_zero_saved_picks_has_no_picks_status_and_no_mean(self):
        result = evaluate_selections(
            saved_snapshot({}),
            daily(SIGNAL_DATE, {'600000.SH': 10.}),
            daily(EVALUATION_DATE, {'600000.SH': 11.}),
            factors(SIGNAL_DATE, {'600000.SH': 1.}),
            factors(EVALUATION_DATE, {'600000.SH': 1.}),
            EVALUATION_DATE,
        )

        self.assertEqual(len(result['strategies']), 4)
        for group in result['strategies']:
            self.assertEqual(group['status'], 'no_picks')
            self.assertEqual((group['selected_count'], group['settled_count']), (0, 0))
            self.assertEqual((group['up_count'], group['down_count'], group['flat_count']), (0, 0, 0))
            self.assertIsNone(group['mean_return_pct'])
            self.assertEqual(group['rows'], [])

    def test_previous_open_date_uses_friday_for_a_monday_evaluation(self):
        calendar = pd.DataFrame([
            {'exchange': 'SSE', 'cal_date': '20260904', 'is_open': 1},
            {'exchange': 'SSE', 'cal_date': '20260905', 'is_open': 0},
            {'exchange': 'SSE', 'cal_date': '20260906', 'is_open': 0},
            {'exchange': 'SSE', 'cal_date': EVALUATION_DATE, 'is_open': 1},
            {'exchange': 'SSE', 'cal_date': '20260908', 'is_open': 1},
        ])
        original = calendar.copy(deep=True)

        self.assertEqual(previous_open_date(calendar, EVALUATION_DATE), SIGNAL_DATE)
        pd.testing.assert_frame_equal(calendar, original)

    def test_snapshot_and_all_market_frames_are_not_modified(self):
        snapshot = saved_snapshot({'leaders': [
            {'ts_code': '600000.SH', 'name': '不可变输入', 'close': 10., 'rank': 1},
        ]})
        inputs = [
            daily(SIGNAL_DATE, {'600000.SH': 10.}),
            daily(EVALUATION_DATE, {'600000.SH': 10.5}),
            factors(SIGNAL_DATE, {'600000.SH': 1.}),
            factors(EVALUATION_DATE, {'600000.SH': 1.}),
        ]
        snapshot_before = copy.deepcopy(snapshot)
        frames_before = [frame.copy(deep=True) for frame in inputs]

        evaluate_selections(snapshot, *inputs, EVALUATION_DATE)

        self.assertEqual(snapshot, snapshot_before)
        for actual, expected in zip(inputs, frames_before):
            pd.testing.assert_frame_equal(actual, expected)


if __name__ == '__main__':
    unittest.main()
