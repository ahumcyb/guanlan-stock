import unittest
import numpy as np
import pandas as pd
from tests.test_strategy import bars
from research.signals import make_signals


def fixture(n=110):
    frames=[]
    for i in range(8):
        x=bars(n);x['ts_code']=f'{i+1:06}.SZ';x['amount']=200000.+i*30000
        frames.append(x)
    daily=pd.concat(frames,ignore_index=True)
    factors=daily[['ts_code','trade_date']].copy();factors['adj_factor']=1.
    limits=daily[['ts_code','trade_date']].copy();limits['up_limit']=daily.pre_close*1.1;limits['down_limit']=daily.pre_close*.9
    status=pd.DataFrame(columns=['ts_code','trade_date'])
    dates=sorted(daily.trade_date.unique())
    return daily,factors,limits,status,dates


class ResearchSignalTests(unittest.TestCase):
    def test_liquid_mature_stocks_actually_generate_nonempty_choices(self):
        d,f,l,s,dates=fixture()
        result=make_signals(d,f,l,s,dates,dates)
        self.assertEqual(result['eligible_count'][-1],8)
        self.assertEqual(int((result['pick_liquidity'][-1]>=0).sum()),5)
        self.assertEqual(int((result['pick_low_vol_60'][-1]>=0).sum()),4)

    def test_future_bars_and_status_do_not_change_past_choices(self):
        d,f,l,s,dates=fixture();cutoff=dates[99]
        before=make_signals(d[d.trade_date<=cutoff],f[f.trade_date<=cutoff],l[l.trade_date<=cutoff],s,dates[:100],dates[:100])
        d.loc[d.trade_date>cutoff,['open','high','low','close']]*=2
        s=pd.DataFrame({'ts_code':['000008.SZ'],'trade_date':[dates[-1]]})
        after=make_signals(d,f,l,s,dates,dates)
        for key in before:
            if key.startswith('pick_'):np.testing.assert_array_equal(before[key],after[key][:100])

    def test_current_names_do_not_decide_historical_membership(self):
        d,f,l,s,dates=fixture();a=make_signals(d,f,l,s,dates,dates)
        d['name']='*ST future name';b=make_signals(d,f,l,s,dates,dates)
        np.testing.assert_array_equal(a['pick_low_vol_60'],b['pick_low_vol_60'])

    def test_known_st_and_unknown_status_date_cannot_enter(self):
        d,f,l,s,dates=fixture();s=pd.DataFrame({'ts_code':['000008.SZ'],'trade_date':[dates[-1]]})
        a=make_signals(d,f,l,s,dates,dates)
        code=list(a['codes']).index('000008.SZ')
        for key in a:
            if key.startswith('pick_'):self.assertNotIn(code,a[key][-1])
        b=make_signals(d,f,l,s,dates,dates[:-1])
        for key in b:
            if key.startswith('pick_'):self.assertTrue((b[key][-1]==-1).all())
