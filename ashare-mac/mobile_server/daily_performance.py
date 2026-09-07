"""Evaluate a previously saved shortlist against the following trading close."""
import math
from engine.close_proof import valid_date
from engine.intraday import CODE
from .artifacts import valid_strategy_group


def positive(value):
    if isinstance(value,bool):return None
    try:value=float(value)
    except (ValueError,TypeError):return None
    return value if math.isfinite(value) and value>0 else None


def previous_open_date(calendar,date):
    if not valid_date(date) or not {'exchange','cal_date','is_open'}.issubset(calendar):return None
    opened=calendar[(calendar.exchange=='SSE') & (calendar.is_open==1)].cal_date.astype(str)
    if date not in set(opened):return None
    previous=[value for value in opened if valid_date(value) and value<date]
    return max(previous) if previous else None


def price_map(frame,date,field):
    if not {'ts_code','trade_date',field}.issubset(frame):return {}
    selected=frame.loc[frame.trade_date.astype(str)==date,['ts_code',field]]
    if selected.ts_code.duplicated().any():raise ValueError('结算行情存在重复代码')
    return {row['ts_code']:positive(row[field]) for row in selected.to_dict(orient='records')}


def validate_selections(snapshot):
    if not isinstance(snapshot,dict) or not valid_date(snapshot.get('date')):raise ValueError('精选快照日期无效')
    groups=snapshot.get('strategies')
    if (not isinstance(groups,list) or not all(isinstance(row,dict) for row in groups)
            or not valid_strategy_group([row.get('id') for row in groups])):
        raise ValueError('精选快照策略集合无效')
    for group in groups:
        picks=group.get('picks')
        if (not isinstance(picks,list) or len(picks)>10 or not isinstance(group.get('name'),str)
                or len(group['name'])>80):raise ValueError('精选快照数量或名称无效')
        codes=set()
        for row in picks:
            if not isinstance(row,dict):raise ValueError('精选快照股票无效')
            code=row.get('ts_code')
            if (not isinstance(code,str) or not CODE.fullmatch(code) or code in codes
                    or positive(row.get('close')) is None or not isinstance(row.get('name'),str)):
                raise ValueError('精选快照股票无效')
            codes.add(code)


def evaluate_selections(snapshot,previous_daily,current_daily,previous_factors,current_factors,evaluation_date):
    validate_selections(snapshot);signal_date=snapshot['date']
    if not valid_date(evaluation_date) or signal_date>=evaluation_date:raise ValueError('结算日期顺序无效')
    before=price_map(previous_daily,signal_date,'close');after=price_map(current_daily,evaluation_date,'close')
    factor_before=price_map(previous_factors,signal_date,'adj_factor')
    factor_after=price_map(current_factors,evaluation_date,'adj_factor')
    groups=[]
    for group in snapshot['strategies']:
        rows=[];returns=[]
        for pick in group['picks']:
            code=pick['ts_code'];p0=before.get(code);p1=after.get(code)
            a0=factor_before.get(code);a1=factor_after.get(code)
            reason=None
            if p0 is None:reason='缺少上一交易日有效收盘价'
            elif abs(p0-float(pick['close']))>1e-6:reason='历史行情与已保存精选价格不一致'
            elif p1 is None:reason='缺少本日有效行情，可能停牌或数据未齐'
            elif a0 is None:reason='缺少上一交易日有效复权因子'
            elif a1 is None:reason='缺少本日有效复权因子'
            value=None
            if reason is None:
                try:value=(p1*a1/(p0*a0)-1)*100
                except (OverflowError,ZeroDivisionError):value=None
                if value is None or not math.isfinite(value):reason='复权观察涨跌计算无效';value=None
                elif abs(value)<=1e-8:value=0.
            if value is not None:returns.append(value)
            rows.append(dict(ts_code=code,name=pick['name'][:30],status='settled' if value is not None else 'unsettled',
                return_pct=value,reason=reason,previous_close=p0,current_close=p1,
                previous_adj_factor=a0,current_adj_factor=a1))
        total=len(rows);settled=len(returns)
        groups.append(dict(id=group['id'],name=group['name'],selected_count=total,settled_count=settled,
            status='no_picks' if not total else ('complete' if settled==total else 'partial'),
            up_count=sum(value>1e-8 for value in returns),down_count=sum(value < -1e-8 for value in returns),
            flat_count=sum(abs(value)<=1e-8 for value in returns),
            mean_return_pct=sum(returns)/total if total and settled==total else None,rows=rows))
    return dict(signal_date=signal_date,evaluation_date=evaluation_date,basis='adjusted_close_to_close',
                status='available',strategies=groups)


def collect_previous_performance(root,market,date,current_frames):
    import pandas as pd
    from .selection_snapshots import find_previous_snapshot,digest
    from .artifacts import STRATEGIES
    unavailable=dict(signal_date=None,evaluation_date=date,basis='adjusted_close_to_close',
                     status='unavailable',strategies=[],message='未找到可验证的上一交易日精选，未结算策略表现。')
    try:
        calendar=pd.read_parquet(market/'raw/trade_cal.parquet',columns=['exchange','cal_date','is_open'])
        previous=previous_open_date(calendar,date)
        if previous is None:
            return dict(unavailable,message='交易日历不足，未确定上一交易日，暂不结算。')
        unavailable['signal_date']=previous
        snapshot=find_previous_snapshot(root,previous,date)
        if snapshot is None:return unavailable
        prices=pd.read_parquet(market/'raw/daily.parquet',columns=['ts_code','trade_date','close'],filters=[('trade_date','==',previous)])
        factors=pd.read_parquet(market/'raw/adj_factor.parquet',columns=['ts_code','trade_date','adj_factor'],filters=[('trade_date','==',previous)])
        result=evaluate_selections(snapshot,prices,current_frames['daily'],factors,current_frames['adj_factor'],date)
        result.update(source_generation=snapshot['generation'],source_data_revision=snapshot['data_revision'],
            snapshot_sha256=digest(snapshot),timing_basis=snapshot['timing_basis'],
            new_strategy_ids=[strategy for strategy in STRATEGIES if strategy not in {g['id'] for g in snapshot['strategies']}],
            message='上一交易日保存的精选，从昨收至今收计算复权观察涨跌；等权均值未计交易费用、仓位及成交约束。')
        return result
    except (OSError,ValueError,KeyError,TypeError,AttributeError):
        return dict(unavailable,message='历史精选或结算数据未通过校验，保留未结算状态。')
