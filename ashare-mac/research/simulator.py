"""Funded long-only daily ledger. Every stage starts flat and ends without peeking."""
from collections import Counter
import math
import numpy as np


def fee(notional, config, sell=False):
    return (max(config['minimum_commission'],notional*config['commission'])
            + notional*(config['transfer_fee']+(config['stamp_duty'] if sell else 0)))


def buy_shares(budget, price, config):
    lot=config['lot_size'];shares=int(budget/price/lot)*lot
    while shares>0 and shares*price+fee(shares*price,config)>budget:shares-=lot
    return shares


def cash_profit_factor(trades):
    gains=sum(t['pnl'] for t in trades if t['pnl']>0)
    losses=-sum(t['pnl'] for t in trades if t['pnl']<0)
    return gains/losses if losses else None


def simulate(market, picks, start, end, horizon, phase, config):
    if not (0<=start<=end<len(market['dates']) and horizon in (1,3,5) and 0<=phase<horizon):
        raise ValueError('Invalid simulation interval')
    dates=market['dates'];cash=float(config['capital']);held={};trades=[];curve=[];skips=Counter()
    final_signal=end-config['purge_sessions']

    def tradable(day, code):
        values=[market[k][day,code] for k in ['open','vol','factor','up_limit','down_limit']]
        return all(math.isfinite(v) and v>0 for v in values) and values[-2]>values[-1]

    def mark(position, day, column):
        code=position['code'];raw=market[column][day,code];factor=market['factor'][day,code]
        if math.isfinite(raw) and raw>0 and math.isfinite(factor) and factor>0:
            position['mark']=raw*factor/position['entry_factor']
            position['mark_date']=str(dates[day]);position['mark_source']=column
        return position['shares']*position['mark']

    for day in range(start,end+1):
        for code,position in list(held.items()):
            if day<position['target']:continue
            if not tradable(day,code):continue
            price=math.floor(market['open'][day,code]*(1-config['slippage'])*100+1e-8)/100
            if price<=market['down_limit'][day,code]+.001:continue
            proceeds=position['shares']*price*market['factor'][day,code]/position['entry_factor']
            exit_fee=fee(proceeds,config,sell=True);cash+=proceeds-exit_fee
            pnl=proceeds-exit_fee-position['spent']
            trades.append({'code':str(market['codes'][code]),'signal_date':str(dates[position['signal']]),
                'entry_date':str(dates[position['entry']]),'exit_date':str(dates[day]),'shares':position['shares'],
                'buy_price':position['buy_price'],'sell_price':price,'buy_fee':position['buy_fee'],
                'sell_fee':exit_fee,'invested':position['spent'],'pnl':pnl,
                'net_return':pnl/position['spent'],'delay':day-position['target']})
            del held[code]
        signal=day-1
        if start<=signal<=final_signal and (signal-start)%horizon==phase:
            opening_nav=cash+sum(mark(p,day,'open') for p in held.values())
            budget=opening_nav/config['positions']
            for raw_code in picks[signal]:
                code=int(raw_code)
                if code<0:continue
                if code in held or len(held)>=config['positions']:
                    skips['occupied']+=1;continue
                if not market['status_known'][day] or market['st'][day,code]:
                    skips['st_or_unknown_status']+=1;continue
                if not tradable(day,code):skips['missing_entry']+=1;continue
                previous=market['pre_close'][day,code]
                if not math.isfinite(previous) or previous<=0:skips['missing_entry']+=1;continue
                if market['open'][day,code]/previous>1.03:skips['gap']+=1;continue
                price=math.ceil(market['open'][day,code]*(1+config['slippage'])*100-1e-8)/100
                if price>=market['up_limit'][day,code]-.001:skips['limit_up']+=1;continue
                shares=buy_shares(min(budget,cash),price,config)
                if not shares:skips['lot_or_cash']+=1;continue
                buy_fee=fee(shares*price,config);spent=shares*price+buy_fee;cash-=spent
                held[code]={'code':code,'signal':signal,'entry':day,'target':day+horizon,'shares':shares,
                            'buy_price':price,'buy_fee':buy_fee,'spent':spent,
                            'entry_factor':market['factor'][day,code],'mark':price,
                            'mark_date':str(dates[day]),'mark_source':'entry'}
            if cash < -1e-7:raise AssertionError('Portfolio borrowed cash')
        nav=cash+sum(mark(p,day,'close') for p in held.values())
        curve.append({'date':str(dates[day]),'nav':nav,'cash':cash,'positions':len(held)})
    # No price after end is accessed, even when a suspension lasts longer than purge.
    values=np.array([config['capital'],*[row['nav'] for row in curve]])
    returns=values[1:]/values[:-1]-1
    net=np.array([t['net_return'] for t in trades]);wins=net[net>0];losses=net[net<0]
    summary={'return':float(values[-1]/config['capital']-1),
        'max_drawdown':float((values/np.maximum.accumulate(values)-1).min()),
        'trades':len(trades),'win_rate':float((net>0).mean()) if len(net) else None,
        'mean_trade':float(net.mean()) if len(net) else None,
        'average_win':float(wins.mean()) if len(wins) else None,
        'average_loss':float(losses.mean()) if len(losses) else None,
        'profit_factor':cash_profit_factor(trades),
        'daily_mean':float(returns.mean()),'daily_std':float(returns.std(ddof=1)) if len(returns)>1 else 0.,
        'unresolved':len(held),'cash_if_open_positions_worth_zero':cash,
        'fees':float(sum(t['buy_fee']+t['sell_fee'] for t in trades)+sum(p['buy_fee'] for p in held.values())),
        'skips':dict(skips)}
    return {'summary':summary,'equity':curve,'trades':trades,
            'open_positions':[{'code':str(market['codes'][p['code']]),'entry_date':str(dates[p['entry']]),
                               'shares':p['shares'],'marked_value':p['shares']*p['mark'],
                               'mark_date':p['mark_date'],'mark_source':p['mark_source']} for p in held.values()]}
