"""Eight fixed daily hypotheses. No learned weights and no future return columns."""
import numpy as np
import pandas as pd
from engine.data import FIELDS
from engine.strategy import features, classify

NAMES={'liquidity':'成交额基准','low_vol_20':'流动性低波动20','low_vol_60':'流动性低波动60',
       'momentum_20':'风险调整动量20','momentum_60':'风险调整动量60',
       'reversal_3':'趋势内三日反转','reversal_5':'趋势内五日反转',
       'low_vol_reversal':'低波动三日回撤','breakout_20':'二十日放量突破',
       'legacy_leaders':'原流动性趋势（统一池）','legacy_pullback':'原缩量回踩（统一池）',
       'legacy_golden_pit':'原黄金坑（统一池）'}


def make_signals(daily, factors, limits, status, dates, known_status_dates, positions=5, liquidity_fraction=.4):
    # No current stock list, name, ST label, listing date or sector enters a past decision.
    bars=daily.loc[daily.ts_code.str.fullmatch(r'(00\d{4}\.SZ|60\d{4}\.SH)'),FIELDS['daily']].copy()
    bars['name']='研究股票';bars['industry']='unclassified';bars['list_date']='19000101'
    x=features(bars,market_dates=dates)
    x=x.merge(factors,on=['ts_code','trade_date'],how='left',validate='one_to_one')
    x=x.merge(limits,on=['ts_code','trade_date'],how='left',validate='one_to_one')
    keys=pd.MultiIndex.from_frame(x[['ts_code','trade_date']])
    st_keys=pd.MultiIndex.from_frame(status[['ts_code','trade_date']].drop_duplicates())
    x['is_st']=keys.isin(st_keys)
    known=set(known_status_dates)
    available=(x.trade_date.isin(known) & ~x.is_st & (x.adj_factor>0)
               & (x.up_limit>x.down_limit) & (x.down_limit>0))
    # Keep features causal and intact; deny classification when D-day constraints are unknown.
    x['observations']=x.observations.where(available,0)
    leaders=classify(x,'leaders');base=leaders.eligible
    date=x.trade_date;group=x.groupby('ts_code',sort=False)
    for n in (20,60):
        x[f'vol{n}']=group.ret1.rolling(n,min_periods=n).std(ddof=1).reset_index(level=0,drop=True).sort_index()
    x['ret3']=x.price/group.price.shift(3)-1
    previous_high20=group.adj_high.rolling(20,min_periods=20).max().reset_index(level=0,drop=True).sort_index().groupby(x.ts_code).shift(1)
    previous_amount20=group.amount20.shift(1)
    quota=np.ceil(base.groupby(date).transform('sum')*liquidity_fraction)
    # x is in code/date order. 'first' therefore breaks equal amounts by ascending code.
    amount_rank=x.amount20.where(base).groupby(date).rank(ascending=False,method='first')
    liquid=base & (amount_rank<=quota)
    vol_rank=x.vol60.where(liquid).groupby(date).rank(ascending=True,method='first')
    low_vol=liquid & (vol_rank<=np.ceil(liquid.groupby(date).transform('sum')*.5))
    trend=x.price>x.ma60
    reversal_day=(x.ret1>-.05) & (x.ret1<=.03)
    masks={'liquidity':base,'low_vol_20':liquid,'low_vol_60':liquid}
    scores={'liquidity':x.amount20,'low_vol_20':-x.vol20,'low_vol_60':-x.vol60}
    for n in (20,60):
        masks[f'momentum_{n}']=liquid & trend & (x[f'ret{n}']>0) & (x.ret1<=.05)
        scores[f'momentum_{n}']=x[f'ret{n}']/x[f'vol{n}'].replace(0,np.nan)
    for n in (3,5):
        masks[f'reversal_{n}']=liquid & trend & x[f'ret{n}'].between(-.10,0,inclusive='left') & reversal_day
        scores[f'reversal_{n}']=-x[f'ret{n}']
    masks['low_vol_reversal']=masks['reversal_3'] & low_vol
    scores['low_vol_reversal']=-x.ret3
    masks['breakout_20']=(liquid & trend & (x.price>previous_high20)
                           & (x.amount>=1.2*previous_amount20) & (x.ret1<=.07))
    scores['breakout_20']=x.ret60/x.vol60.replace(0,np.nan)
    codes=np.array(sorted(x.ts_code.unique()));date_ids={d:i for i,d in enumerate(dates)}
    code_ids={c:i for i,c in enumerate(codes)}
    output={'dates':np.array(dates),'codes':codes,'status_known':np.array([d in known for d in dates])}

    def choose(mask,score):
        rows=x.loc[mask & score.notna(),['trade_date','ts_code']].copy()
        rows['score']=score.loc[rows.index]
        rows=rows.sort_values(['trade_date','score','ts_code'],ascending=[True,False,True]).groupby('trade_date',sort=False).head(positions)
        rank=rows.groupby('trade_date',sort=False).cumcount()
        result=np.full((len(dates),positions),-1,dtype=np.int32)
        result[rows.trade_date.map(date_ids).to_numpy(dtype=int),rank.to_numpy()]=rows.ts_code.map(code_ids).to_numpy(dtype=int)
        return result

    for name in masks:output['pick_'+name]=choose(masks[name],scores[name])
    # Context only: old rule logic gets the same historical main-board pool, top 5 and ledger.
    # No present-day industry cap is imposed, so these are explicitly labelled unified-pool comparisons.
    output['pick_legacy_leaders']=choose(leaders.confirmed,leaders.score)
    del leaders
    for strategy in ['pullback','golden_pit']:
        classified=classify(x,strategy)
        output['pick_legacy_'+strategy]=choose(classified.confirmed,classified.score)
        del classified
    x['research_eligible']=base
    mapping={'open':'open','close':'close','pre_close':'pre_close','vol':'vol','factor':'adj_factor',
             'up_limit':'up_limit','down_limit':'down_limit','st':'is_st',
             'vol20':'vol20','vol60':'vol60','ret3':'ret3','ret5':'ret5','ret20':'ret20','ret60':'ret60',
             'amount20':'amount20','atr':'atr','eligible':'research_eligible'}
    for name,column in mapping.items():
        frame=x.pivot(index='trade_date',columns='ts_code',values=column).reindex(index=dates,columns=codes)
        output[name]=frame.fillna(False).to_numpy(dtype=bool) if name in ['st','eligible'] else frame.to_numpy(dtype=float)
    output['eligible_count']=base.groupby(date).sum().reindex(dates,fill_value=0).to_numpy()
    return output
