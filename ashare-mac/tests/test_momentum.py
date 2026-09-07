import unittest
import numpy as np
import pandas as pd
from tests.test_strategy import bars
from engine.strategy import features, classify, select_day
from engine.momentum import add_constraints
from research.signals import make_signals


def fixture(n=110):
    frames=[]
    for i in range(20):
        row=bars(n);row['ts_code']=f'{i+1:06}.SZ'
        row['amount']=200000+i*15000
        frames.append(row)
    daily=pd.concat(frames,ignore_index=True)
    factors=daily[['ts_code','trade_date']].copy();factors['adj_factor']=1.
    limits=daily[['ts_code','trade_date']].copy()
    limits['up_limit']=daily.pre_close*1.1;limits['down_limit']=daily.pre_close*.9
    return daily,factors,limits


class MomentumTests(unittest.TestCase):
    def signals(self,d,f,l):
        return classify(add_constraints(features(d),f,l),'momentum_60')

    def test_latest_top_five_matches_frozen_research_and_keeps_same_industry(self):
        d,f,l=fixture();dates=sorted(d.trade_date.unique())
        research=make_signals(d,f,l,pd.DataFrame(columns=['ts_code','trade_date']),dates,dates)
        expected=[str(research['codes'][i]) for i in research['pick_momentum_60'][-1] if i>=0]
        live=self.signals(d,f,l);chosen=select_day(live[live.trade_date==dates[-1]])
        self.assertEqual(len(chosen),5)
        self.assertEqual(chosen.ts_code.tolist(),expected)
        self.assertTrue(live.score.between(0,100).all())
        self.assertEqual(chosen.industry.nunique(),1)

    def test_future_data_does_not_change_previous_rankings(self):
        d,f,l=fixture(120);cutoff=sorted(d.trade_date.unique())[99]
        columns=['ts_code','trade_date','eligible','confirmed','score','momentum_ratio','vol60']
        before=self.signals(d[d.trade_date<=cutoff],f,l)
        d.loc[d.trade_date>cutoff,['open','high','low','close']]*=2
        after=self.signals(d,f,l)
        pd.testing.assert_frame_equal(before[columns].reset_index(drop=True),after.loc[after.trade_date<=cutoff,columns].reset_index(drop=True))

    def test_constraints_and_main_board_membership_are_required(self):
        d,f,l=fixture();date=d.trade_date.max();code='000020.SZ'
        f=f[~((f.ts_code==code)&(f.trade_date==date))]
        extra=bars();extra['ts_code']='300001.SZ';extra['amount']=1e9
        out=self.signals(pd.concat([d,extra],ignore_index=True),f,l)
        self.assertFalse(out.loc[(out.ts_code==code)&(out.trade_date==date),'eligible'].any())
        self.assertFalse(out.loc[out.ts_code=='300001.SZ','eligible'].any())
        self.assertFalse(classify(features(d),'momentum_60').eligible.any())

    def test_high_daily_rise_waits_and_raw_ratio_controls_selection(self):
        d,f,l=fixture();out=self.signals(d,f,l);day=out[out.trade_date==out.trade_date.max()].copy()
        # Display rounding must never replace the raw score order.
        day['confirmed']=True;day['score']=100.
        day['momentum_ratio']=np.arange(len(day),dtype=float)
        self.assertEqual(select_day(day).ts_code.tolist(),day.ts_code.iloc[-5:][::-1].tolist())
        raw=add_constraints(features(d),f,l);last=raw.trade_date==raw.trade_date.max()
        raw.loc[last,'ret1']=.051
        high=classify(raw,'momentum_60')
        self.assertFalse(high.loc[last,'confirmed'].any())
        self.assertTrue(high.loc[last,'watch'].any())
