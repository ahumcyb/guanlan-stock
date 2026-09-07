import unittest

import numpy as np
import pandas as pd

from engine.left_rebound import classify_left
from engine.strategy import features, select_day


def left_bars(code='600000.SH', industry='测试行业'):
    close = np.r_[np.linspace(10., 15., 94), [14.6, 14.2, 13.8, 13.5, 13.2, 12.95]]
    volume = np.full(len(close), 100000.)
    volume[-1] = 80000.
    return pd.DataFrame({
        'ts_code': code,
        'trade_date': pd.bdate_range('20260105', periods=len(close)).strftime('%Y%m%d'),
        'open': close * .998,
        'high': close * 1.01,
        'low': close * .99,
        'close': close,
        'pre_close': np.r_[close[0], close[:-1]],
        'vol': volume,
        'amount': volume * close / 100,
        'name': '测试股票',
        'industry': industry,
        'list_date': '20000101',
    })


def replace_last_price(bars, close):
    result = bars.copy(deep=True)
    index = result.index[-1]
    result.loc[index, ['open', 'high', 'low', 'close']] = [close * .998, close * 1.01, close * .99, close]
    result.loc[index, 'amount'] = result.loc[index, 'vol'] * close / 100
    return result


def prepared(bars, breadth=.5, constraints=True):
    frame = features(bars, market_dates=sorted(bars.trade_date.unique()))
    frame['eligible'] = True
    frame['breadth'] = breadth
    frame['liquidity_rank'] = .9
    frame['momentum_constraints_ok'] = constraints
    frame['down_limit'] = frame.pre_close * .9
    return frame


class LeftReboundTests(unittest.TestCase):
    def test_ordered_pullback_with_contracting_volume_and_a_small_down_day_confirms(self):
        result = classify_left(prepared(left_bars()))
        last = result.iloc[-1]

        self.assertTrue(last.eligible)
        self.assertTrue(last.setup)
        self.assertTrue(last.confirmed)
        self.assertLess(last.ret1, 0)  # The rule does not require an up day.
        self.assertLess(last.price, last.ma10)  # Nor does it require reclaiming MA10.
        self.assertGreaterEqual(last.score, 0)
        self.assertLessEqual(last.score, 100)
        self.assertTrue(result.score.between(0, 100).all())

    def test_chasing_high_volume_weak_breadth_missing_constraints_and_acceleration_are_rejected(self):
        cases = {}

        chase = replace_last_price(left_bars(), 13.6)  # More than +2% from the prior close.
        cases['chase'] = prepared(chase)

        distribution = left_bars()
        distribution.loc[distribution.index[-1], 'vol'] = 120000.
        distribution.loc[distribution.index[-1], 'amount'] = (
            distribution.loc[distribution.index[-1], 'vol'] * distribution.close.iloc[-1] / 100)
        cases['distribution'] = prepared(distribution)

        cases['weak_breadth'] = prepared(left_bars(), breadth=.19)
        cases['missing_constraint_flag'] = prepared(left_bars(), constraints=False)

        missing_limit = prepared(left_bars())
        missing_limit.loc[missing_limit.index[-1], 'down_limit'] = np.nan
        cases['missing_down_limit'] = missing_limit

        locked = prepared(left_bars())
        locked.loc[locked.index[-1], 'down_limit'] = locked.close.iloc[-1]
        cases['closed_at_down_limit'] = locked

        cases['accelerating_decline'] = prepared(replace_last_price(left_bars(), 12.4))

        for name, frame in cases.items():
            with self.subTest(name=name):
                last = classify_left(frame).iloc[-1]
                self.assertFalse(last.confirmed)

    def test_future_extremes_do_not_change_past_signal_or_score(self):
        past = left_bars()
        before = classify_left(prepared(past))
        future_close = np.array([25., 8., 30., 7., 35.])
        future_dates = pd.bdate_range(
            pd.Timestamp(past.trade_date.iloc[-1]) + pd.Timedelta(days=1),
            periods=len(future_close),
        ).strftime('%Y%m%d')
        future = pd.DataFrame({
            'ts_code': past.ts_code.iloc[-1],
            'trade_date': future_dates,
            'open': future_close * .998,
            'high': future_close * 1.01,
            'low': future_close * .99,
            'close': future_close,
            'pre_close': np.r_[past.close.iloc[-1], future_close[:-1]],
            'vol': 100000.,
            'amount': future_close * 1000,
            'name': '测试股票',
            'industry': '测试行业',
            'list_date': '20000101',
        })
        combined = pd.concat([past, future], ignore_index=True)
        after = classify_left(prepared(combined)).iloc[:len(past)]

        columns = ['eligible', 'setup', 'confirmed', 'watch', 'score']
        pd.testing.assert_frame_equal(before[columns].reset_index(drop=True), after[columns].reset_index(drop=True))

    def test_selection_keeps_raw_score_order_with_ten_name_limit_and_two_per_industry(self):
        groups = []
        for index in range(12):
            groups.append(left_bars(code=f'{600000 + index:06d}.SH', industry=f'行业{index // 2}'))
        result = classify_left(prepared(pd.concat(groups, ignore_index=True)))
        day = result[result.trade_date == result.trade_date.max()]

        selected = select_day(day)

        self.assertEqual(len(selected), 10)
        self.assertLessEqual(selected.groupby('industry').size().max(), 2)
        expected = selected.sort_values(['score', 'ts_code'], ascending=[False, True]).ts_code.tolist()
        self.assertEqual(selected.ts_code.tolist(), expected)
        self.assertTrue(selected.confirmed.all())


if __name__ == '__main__':
    unittest.main()
