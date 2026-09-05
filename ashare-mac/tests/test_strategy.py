import unittest
import numpy as np
import pandas as pd
from engine.strategy import features, classify


def bars(n=100):
    close = 10 * np.exp(np.arange(n) * .002 + np.sin(np.arange(n)) * .005)
    return pd.DataFrame(dict(ts_code='000001.SZ',
        trade_date=pd.bdate_range('20260101', periods=n).strftime('%Y%m%d'),
        open=close*.999, high=close*1.01, low=close*.99, close=close,
        pre_close=np.r_[10, close[:-1]], vol=100000, amount=200000,
        name='测试股票', industry='测试行业', list_date='20000101'))


class StrategyTests(unittest.TestCase):
    def test_future_bars_do_not_change_past_features(self):
        full = bars(120)
        a = features(full.iloc[:100]); b = features(full).iloc[:100]
        pd.testing.assert_frame_equal(a.reset_index(drop=True), b.reset_index(drop=True))

    def test_ex_right_reference_prevents_fake_crash(self):
        x = bars(); x.loc[90:, ['open', 'high', 'low', 'close', 'pre_close']] /= 2
        adjusted = features(x)
        self.assertLess(abs(adjusted.iloc[90].ret1), .02)

    def test_history_warmup_is_not_eligible(self):
        out = classify(features(bars(65)))
        self.assertFalse(out.eligible.any())

    def test_st_and_beijing_are_excluded(self):
        a = bars(); a['name'] = '*ST测试'
        b = bars(); b['ts_code'] = '920001.BJ'
        self.assertFalse(classify(features(a)).eligible.any())
        self.assertFalse(classify(features(b)).eligible.any())

    def test_tied_relative_strength_is_neutral(self):
        a = bars(); b = bars(); b['ts_code'] = '000002.SZ'
        out = classify(features(pd.concat([a,b])))
        self.assertTrue((out.loc[out.eligible, 'rs20'] == .5).all())

    def test_market_wide_missing_session_breaks_continuity(self):
        complete=bars(100); dates=complete.trade_date.tolist()
        missing=complete.drop(index=80)
        out=features(missing,market_dates=dates)
        self.assertFalse(out.iloc[-1].continuous60)


if __name__ == '__main__':
    unittest.main()
