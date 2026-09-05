"""Fixed, causal golden-pit rules. Compute only for the after-close strategy."""
import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

METRICS = ['pit_peak_date', 'pit_trough_date', 'pit_depth', 'pit_age',
           'pit_fall_days', 'pit_rebound', 'pit_contraction', 'pit_recovery_volume',
           'pit_peak', 'pit_low', 'ma60_slope', 'ret60']


def classify_pit(x):
    # x is the private copy owned by strategy.classify; common chart columns stay intact.
    numeric = {name: np.full(len(x), np.nan) for name in METRICS[2:-2]}
    peak_dates = np.full(len(x), None, dtype=object)
    trough_dates = np.full(len(x), None, dtype=object)
    valid_path = np.zeros(len(x), dtype=bool)
    for indices in x.groupby('ts_code', sort=False).indices.values():
        if len(indices) < 30: continue
        group = x.iloc[indices]
        high, low = group.adj_high.to_numpy(), group.adj_low.to_numpy()
        price, scale = group.price.to_numpy(), (group.price / group.close).to_numpy()
        amount = group.amount.to_numpy(dtype=float)
        amount3 = pd.Series(amount).rolling(3, min_periods=3).mean().to_numpy()
        amount5 = pd.Series(amount).rolling(5, min_periods=5).mean().to_numpy()
        highs, lows = sliding_window_view(high, 30), sliding_window_view(low, 30)
        # Return-chain roundoff must not make equal traded prices different extrema.
        # Ties choose the latest extreme, so a new test of the bottom resets its age.
        at_peak = np.isclose(highs, highs.max(axis=1)[:, None], rtol=1e-10, atol=0)
        peak_offset = 29 - np.argmax(at_peak[:, ::-1], axis=1)
        after_peak = np.arange(30)[None, :] > peak_offset[:, None]
        later_lows = np.where(after_peak, lows, np.inf)
        at_trough = np.isclose(later_lows, later_lows.min(axis=1)[:, None], rtol=1e-10, atol=0)
        trough_offset = 29 - np.argmax(at_trough[:, ::-1], axis=1)
        start = np.arange(len(highs))
        peak, trough, today = start + peak_offset, start + trough_offset, start + 29
        target = indices[29:]
        values = {
            'pit_depth': 1 - low[trough] / high[peak],
            'pit_age': today - trough,
            'pit_fall_days': trough - peak,
            'pit_rebound': price[today] / low[trough] - 1,
            'pit_contraction': amount3[trough] / np.where(amount5[peak] > 0, amount5[peak], np.nan),
            'pit_recovery_volume': amount[today] / np.where(amount5[today-1] > 0, amount5[today-1], np.nan),
            'pit_peak': high[peak] / scale[today],
            'pit_low': low[trough] / scale[today],
        }
        has_trough = peak_offset < 29
        for name, values_for_day in values.items():
            numeric[name][target] = np.where(has_trough, values_for_day, np.nan)
        dates = group.trade_date.to_numpy()
        peak_dates[target] = np.where(has_trough, dates[peak], None)
        trough_dates[target] = np.where(has_trough, dates[trough], None)
        trading = np.isfinite(amount) & (amount > 0) & (group.vol.to_numpy() > 0)
        valid_path[target] = has_trough & sliding_window_view(trading, 30).all(axis=1)
    for name, values in numeric.items(): x[name] = values
    x['pit_peak_date'], x['pit_trough_date'] = peak_dates, trough_dates
    x['ma60_slope'] = x.ma60 / x.groupby('ts_code', sort=False).ma60.shift(5) - 1
    x['trend_ok'] = (x.price > x.ma60) & (x.ma60_slope > 0)
    x['strength_ok'] = x.ret60.between(0, .60, inclusive='right')
    x['pullback_ok'] = (valid_path & x.pit_depth.between(.08, .20)
                        & x.pit_fall_days.between(3, 20) & x.pit_age.between(2, 8)
                        & x.pit_rebound.between(.03, .12) & (x.price >= x.ma10)
                        & x.extension.between(-.03, .08) & x.ret1.between(-.03, .05))
    x['volume_ok'] = x.pit_contraction <= .8
    x['turn_ok'] = ((x.price >= x.ma20) & x.ret1.between(.003, .05)
                    & (x.close_position >= .6) & (x.pit_recovery_volume >= 1.2))
    x['setup'] = x.eligible & x.trend_ok & x.strength_ok & x.pullback_ok & x.volume_ok
    x['confirmed'] = x.setup & x.turn_ok & (x.breadth >= .4)
    x['watch'] = x.setup & ~x.turn_ok & (x.breadth >= .4)
    x['strength_score'] = (x.ret60 / .30).clip(0, 1) * 20
    x['trend_score'] = ((x.ma60_slope / .015).clip(0, 1) * .5 + x.trend_ok * .5) * 20
    x['position_score'] = ((1 - (x.pit_depth - .12).abs() / .08).clip(0, 1) * 15
                           + (1 - (x.pit_rebound - .06).abs() / .06).clip(0, 1) * 10)
    x['volume_score'] = ((1 - x.pit_contraction) / .6).clip(0, 1) * 20
    x['score'] = x[['strength_score', 'trend_score', 'position_score', 'volume_score', 'risk_score']].sum(axis=1, min_count=5).fillna(0).round(1)
    x.loc[~x.eligible | ~valid_path, 'score'] = 0.
    x['breakout'] = x.pit_peak
    x['invalidation'] = np.maximum(x.pit_low * .99, x.close * (1 - 1.5 * x.atr))
    return x
