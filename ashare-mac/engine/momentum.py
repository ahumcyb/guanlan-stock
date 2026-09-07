"""The frozen 60-session risk-adjusted momentum rule, exposed for observation."""
import numpy as np
import pandas as pd

METRICS = ['ret60', 'vol60', 'momentum_ratio']


def add_constraints(frame, factors, limits):
    x = frame.merge(factors[['ts_code','trade_date','adj_factor']], on=['ts_code','trade_date'],
                    how='left', validate='one_to_one')
    x = x.merge(limits[['ts_code','trade_date','up_limit','down_limit']], on=['ts_code','trade_date'],
                how='left', validate='one_to_one')
    x['momentum_constraints_ok'] = (x.adj_factor.gt(0) & x.down_limit.gt(0) & x.up_limit.gt(x.down_limit)
                                    & np.isfinite(x.adj_factor) & np.isfinite(x.up_limit) & np.isfinite(x.down_limit))
    return x


def classify_momentum(x):
    # Keep all stocks and chart rows for the shared four-strategy publication contract.
    x['strategy_id'] = 'momentum_60'
    x['eligible'] &= (x.ts_code.str.fullmatch(r'(00\d{4}\.SZ|60\d{4}\.SH)')
                       & x.get('momentum_constraints_ok', pd.Series(False, index=x.index)))
    dates = x.trade_date
    counts = x.eligible.groupby(dates).transform('sum')
    # Input is in code/date order, as in the frozen study; amount ties use code order.
    amount_rank = x.amount20.where(x.eligible).groupby(dates).rank(ascending=False, method='first')
    liquid = x.eligible & (amount_rank <= np.ceil(counts * .4))
    x['liquidity_rank'] = (1 - (amount_rank - 1) / counts.replace(0, np.nan)).fillna(0)
    x['vol60'] = (x.groupby('ts_code', sort=False).ret1.rolling(60, min_periods=60).std(ddof=1)
                    .reset_index(level=0, drop=True).sort_index())
    x['momentum_ratio'] = x.ret60 / x.vol60.replace(0, np.nan)
    x['trend_ok'] = x.price > x.ma60
    x['strength_ok'] = x.ret60 > 0
    x['volume_ok'] = liquid
    x['pullback_ok'] = (x.vol60 > 0) & np.isfinite(x.momentum_ratio)
    x['turn_ok'] = x.ret1 <= .05
    x['setup'] = x.eligible & x.trend_ok & x.strength_ok & x.volume_ok & x.pullback_ok
    x['confirmed'] = x.setup & x.turn_ok
    x['watch'] = x.setup & ~x.turn_ok
    # The display percentile is bounded for native clients; selection uses the raw ratio.
    x['score'] = (x.momentum_ratio.where(x.setup).groupby(dates).rank(pct=True, method='min') * 100).fillna(0).round(1)
    x['strength_score'] = x.score
    for name in ['trend_score','position_score','volume_score','risk_score']:
        x[name] = 0.
    x['support'] = x.ma60 / x.price * x.close
    eligible = x[x.eligible]
    breadth = (eligible.price > eligible.ma20).groupby(eligible.trade_date).mean()
    x['breadth'] = dates.map(breadth).fillna(0)  # Context only; no added market-timing gate.
    return x
