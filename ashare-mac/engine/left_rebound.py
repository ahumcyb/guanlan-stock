"""Fixed daily left-side watchlist: oversold location plus easing selling pressure."""
import numpy as np
import pandas as pd

METRICS=['left_rsi5','left_drawdown60','left_volume5','left_ma60_slope10','left_distance_low20']
MARKET_THRESHOLD=.2


def classify_left(frame):
    # The public classifier already supplies its own copy, as for the other rules.
    x=frame
    def roll(column,window,operation='mean'):
        value=x.groupby('ts_code',sort=False)[column].rolling(window,min_periods=window)
        return getattr(value,operation)().reset_index(level=0,drop=True).sort_index()
    def lag(column,n):return x.groupby('ts_code',sort=False)[column].shift(n)
    change=x.groupby('ts_code',sort=False).price.diff()
    gain=change.clip(lower=0).groupby(x.ts_code,sort=False).transform(lambda s:s.ewm(alpha=.2,adjust=False,min_periods=5).mean())
    loss=(-change.clip(upper=0)).groupby(x.ts_code,sort=False).transform(lambda s:s.ewm(alpha=.2,adjust=False,min_periods=5).mean())
    rsi=100-100/(1+gain/loss.replace(0,np.nan))
    x['left_rsi5']=rsi.mask((loss==0)&(gain>0),100).mask((loss==0)&(gain==0),50)
    x['left_drawdown60']=1-x.price/roll('adj_high',60,'max')
    x['left_ma60_slope10']=x.ma60/lag('ma60',10)-1
    previous_volume=roll('vol',5).groupby(x.ts_code,sort=False).shift(1)
    x['left_volume5']=x.vol/previous_volume.replace(0,np.nan)
    low20=roll('adj_low',20,'min')
    x['left_distance_low20']=x.price/low20-1
    constraints=x.get('momentum_constraints_ok',pd.Series(False,index=x.index))
    limit=x.get('down_limit',pd.Series(np.nan,index=x.index))
    x['eligible'] &= constraints.fillna(False) & limit.gt(0) & np.isfinite(limit)
    x['strategy_id']='left_rebound'
    x['trend_ok']=x.left_ma60_slope10>=-.03
    x['strength_ok']=x.ret5.between(-.12,-.03) & x.left_rsi5.le(35)
    x['pullback_ok']=(x.left_drawdown60.between(.10,.25) & x.extension.between(-.12,-.02)
                      & x.left_distance_low20.between(0,.08))
    x['volume_ok']=x.left_volume5.le(.9)
    x['turn_ok']=x.ret1.between(-.04,.02) & x.close_position.ge(.4) & x.close.gt(limit+.001)
    x['setup']=x.eligible & x.trend_ok & x.strength_ok & x.pullback_ok
    x['confirmed']=x.setup & x.volume_ok & x.turn_ok & x.breadth.ge(MARKET_THRESHOLD)
    x['watch']=x.setup & ~x.confirmed & x.breadth.ge(MARKET_THRESHOLD)
    x['strength_score']=(1-(x.left_rsi5-20).abs()/20).clip(0,1)*25
    x['position_score']=((1-(x.left_drawdown60-.15).abs()/.10).clip(0,1)*.5
                         +(1-(x.extension+.08).abs()/.06).clip(0,1)*.5)*25
    x['volume_score']=((.9-x.left_volume5)/.4).clip(0,1)*20
    x['trend_score']=((x.close_position-.4)/.6).clip(0,1)*15
    x['risk_score']=x.liquidity_rank.clip(0,1)*15
    x['score']=x[['strength_score','position_score','volume_score','trend_score','risk_score']].fillna(0).sum(axis=1).clip(0,100).round(1)
    x.loc[~x.eligible,'score']=0.
    x['support']=low20/x.price*x.close
    x['invalidation']=np.maximum(x.support*.98,x.close*(1-2*x.atr))
    return x
