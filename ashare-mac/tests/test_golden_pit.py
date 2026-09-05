import unittest
import numpy as np
import pandas as pd
from engine.strategy import features, classify
from tests.test_strategy import bars


def pit_bars():
    x = bars(120)
    # Established ascent, followed by a 12% pullback and a measured recovery.
    close = np.r_[np.linspace(8, 14, 105), np.linspace(13.9, 12.4, 10),
                  [12.5, 12.65, 12.8, 13.0, 13.35]]
    x['close'] = close
    x['pre_close'] = np.r_[8, close[:-1]]
    x['open'] = close * .995
    x['high'] = close * 1.005
    x['low'] = close * .995
    x['amount'] = 240000.
    x.loc[111:115, 'amount'] = 120000.
    x.loc[119, 'amount'] = 330000.
    x.loc[119, 'high'] = 13.38
    return x


class GoldenPitTests(unittest.TestCase):
    def signal(self, x):
        return classify(features(x), 'golden_pit')

    def test_ordered_contracted_pit_confirms_with_recovery_volume(self):
        x = pit_bars(); last = self.signal(x).iloc[-1]
        self.assertTrue(last.confirmed)
        self.assertEqual(last.pit_peak_date, x.trade_date.iloc[104])
        self.assertEqual(last.pit_trough_date, x.trade_date.iloc[114])
        self.assertEqual(last.pit_age, 5)
        self.assertAlmostEqual(last.pit_contraction, .5)
        self.assertAlmostEqual(last.pit_depth, 1 - (12.4*.995)/(14*1.005))
        self.assertGreater(last.pit_peak, last.close)
        self.assertLess(last.invalidation, last.close)

    def test_no_recovery_volume_is_waiting_not_confirmed(self):
        x = pit_bars(); x.loc[119, 'amount'] = 180000.
        last = self.signal(x).iloc[-1]
        self.assertTrue(last.watch); self.assertFalse(last.confirmed)

    def test_lower_low_today_resets_age_instead_of_reusing_old_bottom(self):
        x = pit_bars(); x.loc[119, 'low'] = 12.
        last = self.signal(x).iloc[-1]
        self.assertEqual(last.pit_age, 0)
        self.assertFalse(last.setup)

    def test_low_before_peak_cannot_be_used_as_pit_bottom(self):
        x = pit_bars(); x.loc[100, 'low'] = 10.
        last = self.signal(x).iloc[-1]
        self.assertEqual(last.pit_trough_date, x.trade_date.iloc[114])

    def test_distribution_missing_amount_and_excessive_rebound_are_rejected(self):
        for mode in ['distribution', 'zero_amount', 'chase']:
            with self.subTest(mode=mode):
                x = pit_bars()
                if mode == 'distribution': x.loc[112:114, 'amount'] = 360000.
                elif mode == 'zero_amount': x.loc[112, 'amount'] = 0.
                else:
                    x.loc[119, ['open', 'high', 'low', 'close']] = [13.9, 14.05, 13.85, 14.]
                self.assertFalse(self.signal(x).iloc[-1].setup)

    def test_future_extreme_bars_do_not_change_past_signals_or_path(self):
        x = pit_bars(); future = bars(125).iloc[120:].copy()
        future.loc[:, ['open', 'high', 'low', 'close']] *= 20
        before = self.signal(x)
        after = self.signal(pd.concat([x, future], ignore_index=True)).iloc[:120]
        pd.testing.assert_frame_equal(before, after)

    def test_ex_right_reference_preserves_pit_shape(self):
        x = pit_bars(); before = self.signal(x).iloc[-1]
        x.loc[110:, ['open', 'high', 'low', 'close', 'pre_close']] /= 2
        after = self.signal(x).iloc[-1]
        for name in ['pit_depth', 'pit_rebound', 'pit_contraction', 'score']:
            self.assertAlmostEqual(before[name], after[name])
        self.assertEqual(before.confirmed, after.confirmed)
        self.assertAlmostEqual(before.pit_peak / 2, after.pit_peak)

    def test_symbols_do_not_share_extrema_or_volume(self):
        a = pit_bars(); b = bars(120); b['ts_code'] = '000002.SZ'
        combined = self.signal(pd.concat([b, a]))
        separate = self.signal(a)
        columns = [c for c in separate if c.startswith('pit_')]
        pd.testing.assert_frame_equal(combined.loc[combined.ts_code == '000001.SZ', columns], separate[columns])

    def test_missing_pit_cannot_receive_partial_match_score(self):
        last = self.signal(bars(120)).iloc[-1]
        self.assertTrue(last.eligible)
        self.assertIsNone(last.pit_trough_date)
        self.assertEqual(last.score, 0)

    def test_equal_extremes_use_latest_date_and_reset_bottom_age(self):
        x = pit_bars(); x.loc[107, 'high'] = x.loc[104, 'high']
        last = self.signal(x).iloc[-1]
        self.assertEqual(last.pit_peak_date, x.trade_date.iloc[107])
        x.loc[119, 'low'] = x.loc[114, 'low']
        last = self.signal(x).iloc[-1]
        self.assertEqual(last.pit_trough_date, x.trade_date.iloc[119])
        self.assertEqual(last.pit_age, 0)
        self.assertFalse(last.setup)

    def test_prior_trend_requires_positive_return_up_to_sixty_percent(self):
        for value, expected in [(0., False), (.60, True), (-.001, False), (.601, False)]:
            frame = features(pit_bars()); frame.loc[119, 'ret60'] = value
            self.assertEqual(bool(classify(frame, 'golden_pit').iloc[-1].strength_ok), expected)


if __name__ == '__main__': unittest.main()
