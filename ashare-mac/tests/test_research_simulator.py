import unittest
import numpy as np
from research.simulator import simulate, buy_shares, cash_profit_factor


def market(n=15):
    result={'dates':np.array([f'202601{i+1:02}' for i in range(n)]),'codes':np.array(['000001.SZ'])}
    for key,value in {'open':10.,'close':10.,'pre_close':10.,'vol':100000.,'factor':1.,'up_limit':11.,'down_limit':9.}.items():
        result[key]=np.full((n,1),value)
    result['st']=np.zeros((n,1),dtype=bool)
    result['status_known']=np.ones(n,dtype=bool)
    return result


CONFIG={'capital':100000,'positions':5,'commission':.00025,'minimum_commission':5.,
        'stamp_duty':.0005,'transfer_fee':.00001,'slippage':.001,'lot_size':100,'purge_sessions':0}


class ResearchSimulatorTests(unittest.TestCase):
    def picks(self,n=15):
        x=np.full((n,5),-1,dtype=int);x[0,0]=0
        return x

    def test_entry_is_next_open_and_exit_respects_t_plus_one(self):
        m=market();m['open'][0,0]=8.
        result=simulate(m,self.picks(),0,14,1,0,CONFIG)
        trade=result['trades'][0]
        self.assertEqual((trade['entry_date'],trade['exit_date']),('20260102','20260103'))
        self.assertEqual(trade['shares']%100,0)
        self.assertEqual(trade['buy_price'],10.01)
        self.assertEqual(trade['sell_price'],9.99)
        self.assertGreaterEqual(trade['buy_fee'],5.)
        self.assertLess(result['summary']['return'],0)

    def test_lot_and_minimum_commission_cannot_overspend_cash(self):
        self.assertEqual(buy_shares(1000.,10.,CONFIG),0)
        count=buy_shares(20000.,10.,CONFIG)
        self.assertEqual(count,1900)

    def test_limit_up_and_gap_leave_cash_without_next_rank_replacement(self):
        for price in [11.,10.31]:
            m=market();m['open'][1,0]=price
            result=simulate(m,self.picks(),0,14,3,0,CONFIG)
            self.assertEqual(len(result['trades']),0)
            self.assertEqual(result['summary']['return'],0)

    def test_limit_down_delays_exit_and_does_not_discard_loss(self):
        m=market();m['open'][4,0]=9.;m['open'][5,0]=9.2
        result=simulate(m,self.picks(),0,14,3,0,CONFIG)
        self.assertEqual(result['trades'][0]['exit_date'],'20260106')
        self.assertEqual(result['trades'][0]['delay'],1)
        self.assertLess(result['trades'][0]['net_return'],-.08)

    def test_suspended_position_is_censored_at_stage_end_not_next_stage_price(self):
        m=market();m['open'][4:10,0]=np.nan;m['close'][4:10,0]=np.nan
        a=simulate(m,self.picks(),0,8,3,0,CONFIG)
        m['open'][9:,0]=1000.;m['close'][9:,0]=1000.
        b=simulate(m,self.picks(),0,8,3,0,CONFIG)
        self.assertEqual(a,b)
        self.assertEqual(a['summary']['unresolved'],1)
        self.assertEqual(len(a['trades']),0)
        self.assertLess(a['summary']['return'],0)

    def test_new_st_at_next_open_is_not_bought(self):
        m=market();m['st'][1,0]=True
        self.assertEqual(simulate(m,self.picks(),0,14,3,0,CONFIG)['summary']['trades'],0)

    def test_holdout_start_cannot_use_previous_stage_signal(self):
        result=simulate(market(),self.picks(),1,14,3,0,CONFIG)
        self.assertEqual(result['summary']['return'],0)

    def test_profit_factor_uses_cash_profit_instead_of_unequal_trade_percentages(self):
        trades=[{'pnl':200.,'net_return':.01},{'pnl':-20.,'net_return':-.02}]
        self.assertEqual(cash_profit_factor(trades),10.)

    def test_more_slippage_can_leave_a_position_locked_at_stage_end(self):
        m=market();m['open'][4:,0]=9.02;m['close'][4:,0]=10.5
        normal=simulate(m,self.picks(),0,8,3,0,CONFIG)
        stress=simulate(m,self.picks(),0,8,3,0,dict(CONFIG,slippage=.002))
        self.assertEqual(normal['summary']['unresolved'],0)
        self.assertEqual(stress['summary']['unresolved'],1)
        self.assertGreater(stress['summary']['return'],0)
