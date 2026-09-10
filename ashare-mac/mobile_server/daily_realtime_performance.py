"""Settle prior-day frozen realtime selections, never rerun yesterday's rules."""
import hashlib
import json
import math

from engine.close_proof import valid_date
from engine.intraday import CODE, local_now
from .daily_performance import positive, previous_open_date, price_map
from .realtime_history import RealtimeArchive

STRATEGIES=[('overnight','一夜持股·正文版'),('golden','黄金半小时·七步法'),('bottom_volume','底部放量')]
MESSAGE=('今日表现按昨收→今收的复权涨跌计算，另列提醒价→今收的复权观察收益。'
         '每个策略独立等权，不跨轮次重复计入，也不将策略相加；未计费用、仓位和实际成交。')


def unknown(identity,name,message):
    return dict(id=identity,name=name,status='unavailable',source_slot=None,source_sha256=None,
                rule_version=None,matched_count=None,picks=[],message=message)


def performance_group(source):
    return dict({key:value for key,value in source.items() if key!='picks'},selected_count=None,
                settled_count=0,up_count=0,down_count=0,flat_count=0,
                mean_return_pct=None,mean_signal_return_pct=None,rows=[])


def performance_result(groups,signal_date,evaluation_date):
    return dict(schema_version=1,signal_date=signal_date,evaluation_date=evaluation_date,basis='adjusted_close_to_close',
        signal_basis='adjusted_signal_to_close',status='available' if any(g['status']!='unavailable' for g in groups) else 'unavailable',
        strategies=groups,message=MESSAGE)


def summary_text(performance):
    lines=['昨日实时策略 · 程序汇总']
    for group in performance['strategies']:
        name=group['name']
        if group['status']=='complete':
            lines.append(f"{name}：今日等权涨跌{group['mean_return_pct']:+.2f}%（{group['up_count']}涨{group['down_count']}跌{group['flat_count']}平），"
                         f"提醒价至今收{group['mean_signal_return_pct']:+.2f}%。")
        elif group['status']=='no_picks':lines.append(name+'：昨日无候选，暂无收益样本。')
        else:lines.append(name+'：未结算，暂不展示整体均值。')
    lines.append('今日涨跌按昨收至今收，提醒价口径另列；均为复权观察，未计费用和实际成交。')
    return '\n'.join(lines)


def valid_report(report,date,slot):
    if (not isinstance(report,dict) or report.get('date')!=date or report.get('slot')!=slot
            or report.get('kind')!='screen' or report.get('status') not in ['ready','empty','blocked']
            or report.get('executor') not in ['mac','server']):raise ValueError('实时归档身份无效')
    generated=positive(report.get('generated_at'))
    if generated is None or type(report['generated_at']) not in [int,float]:raise ValueError('实时归档时间无效')
    clock=local_now(generated)
    if clock.strftime('%Y%m%d')!=date or not slot[-4:]<=clock.strftime('%H%M')<='1503':
        raise ValueError('实时归档不是当时的定时结果')


def valid_picks(picks,identity,report):
    if not isinstance(picks,list) or len(picks)>10:raise ValueError('实时候选数量无效')
    seen=set()
    for row in picks:
        if not isinstance(row,dict):raise ValueError('实时候选无效')
        code=row.get('ts_code');at=positive(row.get('quote_at'))
        if (not isinstance(code,str) or not CODE.fullmatch(code) or code in seen
                or row.get('strategy')!=identity or positive(row.get('price')) is None
                or type(row.get('price')) not in [int,float] or type(row.get('quote_at')) not in [int,float]
                or not isinstance(row.get('name'),str) or len(row['name'])>30
                or at is None or local_now(at).strftime('%Y%m%d')!=report['date']
                or not -15<=float(report['generated_at'])-at<=180):raise ValueError('实时候选价格或时间无效')
        seen.add(code)


def select_groups(archive,signal_date):
    if not valid_date(signal_date):raise ValueError('实时选股日期无效')
    loaded={};groups=[]
    for identity,name in STRATEGIES:
        clocks=['1430'] if identity=='bottom_volume' else ['1450','1445','1430']
        group=unknown(identity,name,'上一交易日没有可核验的已完成定时归档，未结算。')
        for clock in clocks:
            slot=signal_date+'-'+clock
            if slot not in loaded:
                try:
                    report=archive.run(slot);valid_report(report,signal_date,slot);loaded[slot]=report
                except FileNotFoundError:loaded[slot]=None
                except (OSError,ValueError,KeyError,TypeError,OverflowError):loaded[slot]='invalid'
            report=loaded[slot]
            if report is None:continue
            if report=='invalid':
                group['message']='昨日 '+clock[:2]+':'+clock[2:]+' 归档未通过校验，保留未结算状态。'
                break
            try:
                rule=None;matched=None
                if identity=='bottom_volume':
                    bottom=report.get('bottom_volume')
                    if bottom is not None and not isinstance(bottom,dict):raise ValueError('底部放量归档格式无效')
                    if not bottom or bottom.get('status') not in ['ready','empty']:continue
                    picks=bottom['candidates'];rule=bottom.get('rule_version',1);matched=bottom['matched_count']
                    if (type(rule) is not int or rule not in [1,2] or type(matched) is not int
                            or not isinstance(picks,list) or not len(picks)<=matched<=6500
                            or (bottom['status']=='empty')!=(matched==0)
                            or bool(matched)!=bool(picks)):raise ValueError('底部放量归档计数无效')
                    name='底部放量·'+('2.5倍上涨' if rule==2 else '原3倍规则')
                else:
                    if report['status'] not in ['ready','empty'] or report.get('run_state','complete')!='complete':continue
                    picks=report['strategies'][identity]
                    if report['status']=='empty' and picks:raise ValueError('空结果携带候选')
                valid_picks(picks,identity,report)
                digest=hashlib.sha256(json.dumps(report,ensure_ascii=False,sort_keys=True,allow_nan=False,separators=(',',':')).encode()).hexdigest()
                label=clock[:2]+':'+clock[2:]
                message='采用昨日 '+label+' 定时轮次保存的候选。'
                if identity!='bottom_volume' and clock!='1450':message='昨日 14:50 轮次未完成或缺失，采用最后完成的 '+label+' 候选。'
                if identity=='bottom_volume' and matched>len(picks):message+='收益只统计当时展示的前10只，未展示部分无冻结价格，不补算。'
                group=dict(id=identity,name=name,status='selected',source_slot=slot,source_sha256=digest,
                           rule_version=rule,matched_count=matched,picks=picks,message=message)
            except (ValueError,KeyError,TypeError):
                group=unknown(identity,name,'昨日候选归档未通过校验，保留未结算状态。')
            break
        groups.append(group)
    return groups


def evaluate_groups(groups,signal_date,evaluation_date,previous_daily,current_daily,previous_factors,current_factors):
    if not valid_date(signal_date) or not valid_date(evaluation_date) or signal_date>=evaluation_date:
        raise ValueError('实时结算日期顺序无效')
    before=price_map(previous_daily,signal_date,'close');after=price_map(current_daily,evaluation_date,'close')
    a0=price_map(previous_factors,signal_date,'adj_factor');a1=price_map(current_factors,evaluation_date,'adj_factor')
    result=[]
    for source in groups:
        group=performance_group(source)
        if source['status']=='unavailable':result.append(group);continue
        returns=[];signal_returns=[]
        for pick in source['picks']:
            code=pick['ts_code'];p0=before.get(code);p1=after.get(code);f0=a0.get(code);f1=a1.get(code)
            reason=None;value=None;signal_value=None;signal_price=float(pick['price'])
            if p0 is None:reason='缺少上一交易日有效收盘价'
            elif p1 is None:reason='缺少本日有效行情，可能停牌或数据未齐'
            elif f0 is None or f1 is None:reason='缺少有效复权因子'
            else:
                try:
                    value=(p1*f1/(p0*f0)-1)*100
                    signal_value=(p1*f1/(signal_price*f0)-1)*100
                    if not math.isfinite(value) or not math.isfinite(signal_value):raise ValueError()
                    value=0. if abs(value)<=1e-8 else value
                    signal_value=0. if abs(signal_value)<=1e-8 else signal_value
                except (ValueError,OverflowError,ZeroDivisionError):
                    reason='复权观察涨跌计算无效';value=signal_value=None
            if value is not None:returns.append(value);signal_returns.append(signal_value)
            group['rows'].append(dict(ts_code=code,name=pick['name'],status='settled' if value is not None else 'unsettled',
                reason=reason,return_pct=value,signal_return_pct=signal_value,signal_price=signal_price,quote_at=pick['quote_at'],
                previous_close=p0,current_close=p1,previous_adj_factor=f0,current_adj_factor=f1))
        total=len(group['rows']);settled=len(returns)
        group.update(selected_count=total,settled_count=settled,
            status='no_picks' if not total else ('complete' if settled==total else 'partial'),
            up_count=sum(x>1e-8 for x in returns),down_count=sum(x< -1e-8 for x in returns),flat_count=sum(abs(x)<=1e-8 for x in returns),
            mean_return_pct=sum(returns)/total if total and settled==total else None,
            mean_signal_return_pct=sum(signal_returns)/total if total and settled==total else None)
        result.append(group)
    return performance_result(result,signal_date,evaluation_date)


def collect_realtime_performance(root,market,date,current_frames):
    import pandas as pd
    from pathlib import Path
    previous=None;groups=[unknown(identity,name,'交易日历或结算行情不足，未结算。') for identity,name in STRATEGIES]
    try:
        calendar=pd.read_parquet(market/'raw/trade_cal.parquet',columns=['exchange','cal_date','is_open'])
        previous=previous_open_date(calendar,date)
        if previous is None:raise ValueError('未确定上一交易日')
        groups=select_groups(RealtimeArchive(Path(root)/'jobs/realtime'),previous)
        prices=pd.read_parquet(market/'raw/daily.parquet',columns=['ts_code','trade_date','close'],filters=[('trade_date','==',previous)])
        factors=pd.read_parquet(market/'raw/adj_factor.parquet',columns=['ts_code','trade_date','adj_factor'],filters=[('trade_date','==',previous)])
        return evaluate_groups(groups,previous,date,prices,current_frames['daily'],factors,current_frames['adj_factor'])
    except (OSError,ValueError,KeyError,TypeError,AttributeError):
        # This section must not prevent the otherwise valid close summary.
        return performance_result([performance_group(unknown(g['id'],g['name'],
            '历史提醒或结算数据未通过校验，保留未结算状态。')) for g in groups],previous,date)
