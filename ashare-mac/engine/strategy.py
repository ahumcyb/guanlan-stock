"""Frozen, interpretable short-horizon trend/pullback rules. No fitting."""
import numpy as np
import pandas as pd

VERSION = 'shortline-1.4.0'
STRATEGIES = {'leaders':'流动性趋势', 'pullback':'缩量回踩转强', 'golden_pit':'黄金坑',
              'left_rebound':'左侧低吸', 'momentum_60':'60 日风险调整动量'}
MARKET_THRESHOLDS={'leaders':.4,'pullback':.4,'golden_pit':.4,'left_rebound':.2,'momentum_60':None}


def features(bars: pd.DataFrame, market_dates=None) -> pd.DataFrame:
    x = bars.sort_values(['ts_code', 'trade_date']).reset_index(drop=True).copy()
    groups = x.groupby('ts_code', sort=False)
    x['ret1'] = x.close / x.pre_close - 1
    x['price'] = (1 + x.ret1).groupby(x.ts_code, sort=False).cumprod() * 100
    scale = x.price / x.close
    x['adj_high'] = x.high * scale
    x['adj_low'] = x.low * scale
    x['adj_open'] = x.open * scale
    x['observations'] = groups.cumcount() + 1
    dates = {d: i for i, d in enumerate(market_dates if market_dates is not None else sorted(x.trade_date.unique()))}
    x['market_index'] = x.trade_date.map(dates)

    def roll(column, window, operation='mean'):
        rolling = x.groupby('ts_code', sort=False)[column].rolling(window, min_periods=window)
        return getattr(rolling, operation)().reset_index(level=0, drop=True).sort_index()

    def lag(column, n):
        return x.groupby('ts_code', sort=False)[column].shift(n)

    for n in (10, 20, 60):
        x[f'ma{n}'] = roll('price', n)
    for n in (5, 20, 60):
        x[f'ret{n}'] = x.price / lag('price', n) - 1
    prev = lag('price', 1)
    x['true_range'] = pd.concat([x.adj_high-x.adj_low, (x.adj_high-prev).abs(),
                                (x.adj_low-prev).abs()], axis=1).max(axis=1)
    x['atr'] = roll('true_range', 14) / x.price
    x['amount20'] = roll('amount', 20)
    x['volume_ratio'] = roll('amount', 3) / x.amount20.replace(0, np.nan)
    x['pullback'] = 1 - x.price / roll('adj_high', 10, 'max')
    x['extension'] = x.price / x.ma20 - 1
    x['ma_slope'] = x.ma20 / lag('ma20', 5) - 1
    x['close_position'] = ((x.close-x.low)/(x.high-x.low).replace(0, np.nan)).fillna(0)
    x['continuous60'] = (x.market_index-lag('market_index', 59)) == 59
    x['low5'] = roll('adj_low', 5, 'min') / scale
    x['breakout'] = x.high
    return x


def classify(features_frame: pd.DataFrame, strategy='pullback') -> pd.DataFrame:
    if strategy not in STRATEGIES:
        raise ValueError('未知策略')
    x = features_frame.copy()
    x['eligible'] = (x.ts_code.str.match(r'^(00|30|60|68)\d{4}\.(SH|SZ)$')
        & ~x.name.fillna('').str.contains('ST|退', case=False, regex=True)
        & x.name.notna() & (x.observations >= 80) & x.continuous60
        & (x.amount20 >= 100000) & (x.close >= 3) & (x.atr <= .06)
        & (x.vol > 0) & (x.list_date.fillna('99999999') <= x.trade_date))
    eligible = x[x.eligible]
    ranks = eligible.groupby('trade_date').ret20.rank(method='average')
    sizes = eligible.groupby('trade_date').ret20.transform('count')
    x['rs20'] = ((ranks - .5) / sizes).reindex(x.index).fillna(0)
    breadth = (eligible.price > eligible.ma20).groupby(eligible.trade_date).mean()
    x['breadth'] = x.trade_date.map(breadth).fillna(0)
    x['trend_ok'] = (x.price > x.ma20) & (x.ma20 > x.ma60) & (x.ma_slope > 0)
    x['pullback_ok'] = x.pullback.between(.01, .10) & x.extension.between(0, .08)
    x['volume_ok'] = x.volume_ratio <= .95
    x['strength_ok'] = x.rs20 >= .65
    x['turn_ok'] = (x.ret1 > 0) & (x.close_position >= .55)
    setup = (x.eligible & x.trend_ok & x.pullback_ok & x.volume_ok & x.strength_ok
             & x.ret1.between(-.01, .05))
    x['setup'] = setup
    x['confirmed'] = setup & x.turn_ok & (x.breadth >= .4)
    x['watch'] = setup & ~x.turn_ok & (x.breadth >= .4)
    x['strength_score'] = x.rs20 * 30
    x['trend_score'] = ((x.ma_slope/.025).clip(0, 1)*.5 + x.trend_ok*.5) * 20
    x['position_score'] = (1 - (x.pullback-.04).abs()/.06).clip(0, 1) * 20
    x['volume_score'] = ((1.2-x.volume_ratio)/.7).clip(0, 1) * 15
    x['risk_score'] = ((.06-x.atr)/.05).clip(0, 1) * 15
    x['score'] = x[['strength_score', 'trend_score', 'position_score', 'volume_score', 'risk_score']].sum(axis=1).round(1)
    x.loc[~x.eligible, 'score'] = 0.
    x['support'] = x.ma20 / x.price * x.close
    x['invalidation'] = np.maximum(x.low5, x.close*(1-1.5*x.atr))
    liquidity_ranks=eligible.groupby('trade_date').amount20.rank(method='average')
    x['liquidity_rank']=((liquidity_ranks-.5)/sizes).reindex(x.index).fillna(0)
    if strategy=='leaders':
        x['strength_ok']=x.rs20>=.5
        x['volume_ok']=x.liquidity_rank>=.8
        x['pullback_ok']=x.extension.between(0,.08) & x.ret5.between(-.03,.12)
        x['turn_ok']=(x.price>=x.ma10) & x.ret1.between(0,.05)
        x['setup']=x.eligible & x.trend_ok & x.strength_ok & x.volume_ok & x.pullback_ok
        x['confirmed']=x.setup & x.turn_ok & (x.breadth>=.4)
        x['watch']=x.setup & ~x.turn_ok & (x.breadth>=.4)
        x['volume_score']=((x.liquidity_rank-.8)/.2).clip(0,1)*35
        x['position_score']=0.
        x['score']=x[['strength_score','trend_score','volume_score','risk_score']].sum(axis=1).round(1)
        x.loc[~x.eligible,'score']=0.
    if strategy == 'golden_pit':
        from .golden_pit import classify_pit
        return classify_pit(x)
    if strategy == 'momentum_60':
        from .momentum import classify_momentum
        return classify_momentum(x)
    if strategy == 'left_rebound':
        from .left_rebound import classify_left
        return classify_left(x)
    return x


def select_day(day: pd.DataFrame, limit=10) -> pd.DataFrame:
    if 'strategy_id' in day and not day.empty and day.strategy_id.eq('momentum_60').all():
        return day[day.confirmed].sort_values(['momentum_ratio','ts_code'], ascending=[False,True]).head(min(limit,5)).copy()
    candidates = day[day.confirmed].sort_values(['score', 'ts_code'], ascending=[False, True]).copy()
    candidates['industry'] = candidates.industry.fillna('未分类')
    return candidates[candidates.groupby('industry').cumcount() < 2].head(limit)
