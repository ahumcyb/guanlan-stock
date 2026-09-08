"""Verified cross-day differences; missing history stays unknown."""
import json
import math
from pathlib import Path
from .artifacts import checked_file
from engine.close_proof import valid_date


def market_changes(root,previous_date,current,strong=None):
    if not valid_date(previous_date):return None
    root=Path(root).resolve()
    try:
        from .daily_facts import evidence_hash
        path=root/'jobs/daily/reports'/(previous_date+'.json')
        report=json.loads(checked_file(root,path,128*1024).read_text());evidence=report['evidence']
        if (report.get('schema_version')!=1 or report.get('date')!=previous_date or evidence.get('date')!=previous_date
                or report.get('evidence_sha256')!=evidence_hash(evidence)):return None
        previous=evidence['market']
        keys=['stock_count','turnover_yi','advancers','decliners','breadth','limit_up','limit_down']
        if any(type(row.get(k)) not in [int,float] or not math.isfinite(row[k]) for row in [previous,current] for k in keys):return None
        if previous['turnover_yi']<=0:return None
        before_names={row['name'] for row in evidence.get('sectors_strong',[])}
        now_names={row['name'] for row in strong or []}
        return dict(previous_date=previous_date,stock_count_before=previous['stock_count'],stock_count_after=current['stock_count'],
            turnover_yi_before=previous['turnover_yi'],turnover_yi_after=current['turnover_yi'],
            turnover_change_pct=round((current['turnover_yi']/previous['turnover_yi']-1)*100,4),
            advancers_change=current['advancers']-previous['advancers'],decliners_change=current['decliners']-previous['decliners'],
            breadth_change_pp=round((current['breadth']-previous['breadth'])*100,4),
            limit_up_change=current['limit_up']-previous['limit_up'],limit_down_change=current['limit_down']-previous['limit_down'],
            entered_strong=sorted(now_names-before_names) if before_names else [],
            left_strong=sorted(before_names-now_names) if now_names else [])
    except (OSError,ValueError,KeyError,TypeError):return None


def selection_changes(strategies,performance,reviews):
    before={group['id']:group for group in performance.get('strategies',[])};result=[]
    for group in strategies:
        identity=group['id'];current={row['ts_code']:row for row in group['picks']}
        status='unavailable' if performance.get('status')!='available' else ('available' if identity in before else 'new_strategy')
        item=dict(id=identity,name=group['name'],status=status,previous_date=performance.get('signal_date'),added=[],retained=[],removed=[])
        if status!='unavailable':
            previous={row['ts_code']:row for row in before.get(identity,{}).get('rows',[])}
            slim=lambda row:dict(ts_code=row['ts_code'],name=row['name'])
            item['added']=[slim(current[code]) for code in sorted(current.keys()-previous.keys())]
            item['retained']=[slim(current[code]) for code in sorted(current.keys()&previous.keys())]
            item['removed']=[dict(slim(previous[code]),reason=reviews.get(identity,{}).get(code,'本期未进入精选，具体条件暂不可复核'))
                             for code in sorted(previous.keys()-current.keys())]
        result.append(item)
    return result


def removal_reason(stock,date,quote,threshold,breadth):
    if (stock.get('trade_date')!=date or stock.get('stale') or quote is None
            or not isinstance(stock.get('close'),(int,float)) or abs(stock['close']-float(quote.close))>1e-6):return '当日行情未通过核验，暂不判断条件失效'
    if stock.get('eligible') is False:return '本日未满足基础池或交易数据约束'
    if threshold is not None and breadth<threshold:return '市场宽度未达到本策略门槛'
    labels={'trend_ok':'趋势条件','strength_ok':'强度/超跌条件','pullback_ok':'位置条件','volume_ok':'量能条件','turn_ok':'收盘确认条件'}
    failed=[label for key,label in labels.items() if stock.get(key) is False]
    if failed:return '未满足'+'、'.join(failed)
    if stock.get('state') in ['转强','符合']:return '条件满足，但未进入精选排序或行业限额'
    return '本期未进入精选'
