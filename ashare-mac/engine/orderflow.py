"""Dated Datta large-flow confirmation. Unverified order queues are not trades."""
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import numpy as np
from .datta import DattaClient, DattaError, DattaUnavailable, number, source_time

RULE_VERSION=1
POOL_LIMIT=200
METRICS=['flow_net','flow_net_ratio','flow_net3','flow_positive_days','flow_late_return','flow_late_volume']


def decode_flow(snapshot,history,bar,dates,now=None):
    try:
        if snapshot['code']!=1 or history['code']!=1:raise DattaError('资金流接口未成功')
        d=snapshot['data'];date=bar['trade_date'];code=bar['ts_code']
        observed=source_time(d['minTime'])
        if (d['symbol']!=code[:6] or d['market'].lower()!=code[-2:].lower()
                or source_time(d['tradeDay']).strftime('%Y%m%d')!=date or observed.strftime('%Y%m%d')!=date):
            raise DattaError('资金流代码或源日期不一致')
        if now is None:
            if observed.hour<15:raise DattaError('资金流尚未收盘')
        elif not -15<=(now-observed).total_seconds()<=180:raise DattaError('盘中资金流已过时')
        tolerance=.001 if now is None else .005
        if abs(number(d['lastPx'],True)/bar['close']-1)>tolerance:raise DattaError('资金流价格不匹配')
        values={k:number(d[k]) for k in ['superTurnoverIn','superTurnoverOut','largeTurnoverIn','largeTurnoverOut','mainTurnoverIn','mainTurnoverOut']}
        if min(values.values())<0:raise DattaError('资金流金额为负')
        for suffix in ['In','Out']:
            if abs(values['mainTurnover'+suffix]-values['superTurnover'+suffix]-values['largeTurnover'+suffix])>2:
                raise DattaError('资金流分类之和不一致')
        net=number(d['netTurnover']);amount=number(bar['amount'],True)*1000
        if abs(net-values['mainTurnoverIn']+values['mainTurnoverOut'])>2 or max(values.values())>amount*1.02:
            raise DattaError('资金流总额不一致')
        ratio=net/amount
        if abs(ratio-number(d['RatioMain']))>(.002 if now is None else .01):raise DattaError('资金流金额单位未通过核验')
        needed=sorted(set(d for d in dates if d<date))[-2:]
        if len(needed)!=2:raise DattaError('资金流缺少前两交易日历')
        prior={}
        for row in history['data']:
            day=source_time(row['tradeDay']).strftime('%Y%m%d')
            if day in prior:raise DattaError('资金流历史日期重复')
            prior[day]=number(row['netTurnover'])
        if not set(needed).issubset(prior):raise DattaError('资金流历史交易日缺失')
        totals=[prior[d] for d in needed]+[net]
        return dict(flow_net=net,flow_net_ratio=ratio,flow_net3=sum(totals),
                    flow_positive_days=sum(v>0 for v in totals),flow_observed_at=observed.timestamp())
    except DattaError:raise
    except (KeyError,TypeError,ValueError,AttributeError):raise DattaError('资金流字段不完整') from None


def decode_replay(payload,bar):
    """Use only dated cumulative shares/price. Raw amount and order statuses excluded."""
    try:
        day=bar['trade_date']
        segments=[s for s in payload['segments'] if s.get('type')=='tick']
        if str(payload['date'])!=day or len(segments)!=1 or str(segments[0]['date'])!=day:
            raise DattaError('盘口复盘日期不一致')
        ticks=segments[0]['data']
        if not isinstance(ticks,list) or not 3<=len(ticks)<=50000:raise DattaError('盘口复盘记录数无效')
        state={};previous_time=0;previous_volume=0;anchor=None;end=None;first=None
        for row in ticks:
            state.update({k:row[k] for k in ['time','price','volume','prev_close'] if k in row})
            clock=state.get('time');volume=number(state.get('volume'))
            if type(clock) is not int or not 0<=clock<=235959 or clock%100>=60 or clock//100%100>=60:
                raise DattaError('盘口时间无效')
            if clock<previous_time:raise DattaError('盘口时间倒序')
            previous_time=clock
            if clock>150010:continue
            if volume<previous_volume:raise DattaError('盘口累计成交量回退')
            previous_volume=volume
            if volume<=0:continue
            price=number(state.get('price'),True)
            if not bar['low']-.011<=price<=bar['high']+.011 or abs(number(state.get('prev_close'),True)-bar['pre_close'])>.011:
                raise DattaError('盘口价格与日线不一致')
            if first is None:first=clock
            if 142900<=clock<=143000:anchor=(price,volume)
            if 150000<=clock<=150010:end=(price,volume)
        if first is None or first>93000 or anchor is None or end is None:
            raise DattaError('盘口缺少开盘、14:30或收盘锚点')
        if abs(end[0]-bar['close'])>.011 or abs(end[1]/(bar['vol']*100)-1)>.005:
            raise DattaError('盘口收盘量价未与日线对齐')
        return dict(flow_late_return=end[0]/anchor[0]-1,flow_late_volume=(end[1]-anchor[1])/end[1],replay_source='datta_d3')
    except DattaError:raise
    except (KeyError,TypeError,ValueError,AttributeError):raise DattaError('盘口复盘字段不完整') from None



def decode_minutes(rows,bar):
    """Same-provider dated minute replay when D3 is missing or disagrees with totals."""
    from datetime import datetime
    try:
        expected=set(range(571,691))|set(range(781,901));by_minute={}
        for row in rows:
            observed=datetime.fromisoformat(row['time'])
            minute=observed.hour*60+observed.minute
            if (observed.strftime('%Y%m%d')!=bar['trade_date'] or observed.utcoffset().total_seconds()!=28800
                    or observed.second or observed.microsecond or minute in by_minute or row['ts_code']!=bar['ts_code']):
                raise DattaError('分钟复盘日期、代码或主键无效')
            if number(row['vol'])<0 or number(row['amount'])<0:raise DattaError('分钟复盘量额无效')
            by_minute[minute]=row
        if set(by_minute)!=expected:raise DattaError('分钟复盘不含完整240分钟')
        volume=sum(r['vol'] for r in rows);amount=sum(r['amount'] for r in rows)
        if (abs(number(by_minute[900]['close'],True)-bar['close'])>.011 or volume<=0
                or abs(volume/(bar['vol']*100)-1)>.005 or abs(amount/(bar['amount']*1000)-1)>.005):
            raise DattaError('分钟复盘与日线量额不一致')
        return dict(flow_late_return=by_minute[900]['close']/number(by_minute[870]['close'],True)-1,
                    flow_late_volume=sum(r['vol'] for m,r in by_minute.items() if m>870)/volume,replay_source='datta_d6_min1')
    except DattaError:raise
    except (KeyError,TypeError,ValueError,AttributeError,ZeroDivisionError):raise DattaError('分钟复盘字段缺失') from None


def prescreen(x,date):
    valid=(x.eligible & x.trade_date.eq(date) & x.momentum_constraints_ok & x.breadth.ge(.4)
           & x.ret1.between(.003,.05) & x.extension.between(0,.08) & x.ret5.le(.12)
           & x.close_position.ge(.65) & (x.amount/x.amount20).between(1,3)
           & x.close.lt(x.up_limit-.001) & x.close.gt(x.down_limit+.001))
    return x.loc[valid].sort_values(['amount20','ts_code'],ascending=[False,True]).head(POOL_LIMIT).ts_code.tolist()


def flow_pass(e):return e['flow_net']>=20e6 and e['flow_net_ratio']>=.03 and e['flow_net3']>0 and e['flow_positive_days']>=2


def apply_evidence(x,date,codes,evidence,complete):
    x['strategy_id']='orderflow';x['eligible'] &= x.trade_date.eq(date) & x.ts_code.isin(codes)
    for field in METRICS:
        x[field]=x.ts_code.map({c:e.get(field) for c,e in evidence.items()}).where(x.trade_date.eq(date))
    x['trend_ok']=x.price.ge(x.ma20)
    x['strength_ok']=x.flow_net.ge(20e6) & x.flow_net_ratio.ge(.03) & x.flow_net3.gt(0) & x.flow_positive_days.ge(2)
    x['pullback_ok']=x.extension.between(0,.08) & x.ret5.le(.12)
    x['volume_ok']=x.flow_late_volume.ge(.08)
    x['turn_ok']=x.flow_late_return.ge(0) & x.close_position.ge(.65)
    x['setup']=x.eligible & x.strength_ok
    x['confirmed']=x.setup & x.trend_ok & x.pullback_ok & x.volume_ok & x.turn_ok & complete
    x['watch']=x.setup & ~x.confirmed & complete
    x['strength_score']=(x.flow_net_ratio/.15).clip(0,1)*35
    x['trend_score']=(x.flow_positive_days/3).clip(0,1)*15
    x['position_score']=((x.close_position-.5)/.5).clip(0,1)*20
    x['volume_score']=(x.flow_late_volume/.25).clip(0,1)*15
    x['risk_score']=((.06-x.atr)/.05).clip(0,1)*15
    x['score']=x[['strength_score','trend_score','position_score','volume_score','risk_score']].fillna(0).sum(axis=1).clip(0,100).round(1)
    x.loc[~x.eligible,'score']=0.
    if not complete:x['score']=0.
    x['support']=x.ma20/x.price*x.close
    x['invalidation']=np.maximum(x.low5,x.close*(1-1.5*x.atr))
    return x


def collect_daily(x,date,dates,client=None):
    client=client or DattaClient(workers=4);codes=prescreen(x,date)
    bars=x[x.trade_date.eq(date)].set_index('ts_code').to_dict('index');evidence={};failures={};start=time.monotonic()
    def fetch_once(code):
        bar=dict(bars[code],ts_code=code);params=dict(symbol=code[:6],market=code[-2:].lower())
        raw=client.transport('/d6/market/v1/capital/flow/snapshot',params)
        history=client.transport('/d6/market/v1/capital/flow/history',dict(params,limit=10))
        e=decode_flow(raw,history,bar,dates)
        if flow_pass(e):
            try:
                replay=client.transport('/d3/history',dict(date=date,id=code[-2:]+code[:6]))
                e.update(decode_replay(replay,bar))
            except Exception:
                e.update(decode_minutes(client.history(code,'MIN1',date,date),bar))
        e['evidence_sha256']=hashlib.sha256(json.dumps([raw,history,e],sort_keys=True).encode()).hexdigest()
        return e
    def fetch(code):
        # One retry on the same fenced provider; never retry lost ownership.
        for attempt in range(2):
            try:return fetch_once(code)
            except DattaUnavailable:raise
            except Exception:
                if attempt:raise
    # Bounded batches avoid filling an executor with hundreds of unstarted requests.
    with ThreadPoolExecutor(max_workers=4) as pool:
        for offset in range(0,len(codes),4):
            batch=codes[offset:offset+4]
            if time.monotonic()-start>180:
                failures.update({c:'采集超时' for c in codes[offset:]});break
            futures={pool.submit(fetch,c):c for c in batch}
            for future in as_completed(futures):
                code=futures[future]
                try:evidence[code]=future.result()
                except Exception:failures[code]='日期、字段或量价校验未通过'
    base=x[x.trade_date.eq(date) & x.eligible]
    if len(base) and base.momentum_constraints_ok.mean()<.97:failures['_baseline']='当日因子或涨跌停价覆盖不足97%'
    complete=not failures
    status=dict(rule_version=RULE_VERSION,status='complete' if complete else 'incomplete',
        requested=len(codes),verified=len(evidence),replay_verified=sum('flow_late_return' in e for e in evidence.values()),
        date=date,evidence=evidence,failures=failures,
        message=f'大单数据核验 {len(evidence)}/{len(codes)}；'+('已完成限定股票池检查。' if complete else '未完成，本轮不生成大单精选。'))
    return apply_evidence(x,date,codes,evidence,complete),status
