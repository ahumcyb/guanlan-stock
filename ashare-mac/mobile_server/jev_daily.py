"""Post-close JEV plans bound to immutable five-strategy publications."""
import copy
import hashlib
import json
import re
import uuid
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from .artifacts import STRATEGIES,GENERATION,MAX_REPORT,checked_file
from .jev import save,load_record,digest,request_payload,decode,call_api,dispatch_lock,finite
from .realtime_history import prune
from engine.close_proof import valid_date
from engine.snapshot_protocol import REVISION

ZONE=ZoneInfo('Asia/Shanghai')
DESCRIPTIONS={
 'leaders':'Liquid trend continuation: moving averages and relative strength, without excessive extension.',
 'pullback':'Trend pullback with contracting volume followed by strengthening.',
 'golden_pit':'Deep contraction within an earlier uptrend, followed by recovery confirmation.',
 'left_rebound':'Left-side oversold and easing selling pressure. May remain below MA20; do not impose a momentum setup on this strategy.',
 'orderflow':'Dated large-flow persistence with closing price/volume acceptance.'}
METRICS=['score','ret20','rs20','atr','volume_ratio','pullback','extension','amount20','support','breakout','invalidation',
 'left_rsi5','left_drawdown60','left_volume5','left_distance_low20','left_ma60_slope10',
 'pit_depth','pit_age','pit_rebound','flow_net','flow_net_ratio','flow_net3','flow_positive_days','flow_late_return','flow_late_volume']


def current_generation(root):
    target=(root/'current').resolve(strict=True)
    if target.parent!=root.resolve()/'releases' or not GENERATION.fullmatch(target.name):raise ValueError('当前发布版本无效')
    return target.name


def headers(root,generation):
    root=root.resolve()
    if not isinstance(generation,str) or not GENERATION.fullmatch(generation):raise ValueError('发布版本无效')
    folder=root/'releases'/generation;result={}
    for strategy in STRATEGIES:
        h=json.loads(checked_file(root,folder/strategy/'manifest.json',65536).read_text())
        if (h.get('schema_version')!=1 or h.get('generation')!=generation or h.get('strategy')!=strategy
                or not valid_date(h.get('as_of')) or not REVISION.fullmatch(str(h.get('data_revision')))
                or not h['data_revision'].startswith(h['as_of']+'-')
                or type(h.get('report_bytes')) is not int or not 0<h['report_bytes']<=MAX_REPORT):raise ValueError('盘后清单无效')
        result[strategy]=h
    if len({(h['as_of'],h['data_revision']) for h in result.values()})!=1:raise ValueError('盘后版本未对齐')
    return result


def identity(heads):
    first=next(iter(heads.values()))
    return dict(scope='after_close',generation=first['generation'],slot=first['generation'],date=first['as_of'],
                data_revision=first['data_revision'],source_report_shas={k:h['report_sha256'] for k,h in heads.items()})


def load_input(root,generation,calendar):
    heads=headers(root,generation);info=identity(heads);date=info['date']
    close=datetime.strptime(date,'%Y%m%d').replace(hour=15,tzinfo=ZONE)
    days=sorted({d for d in calendar if valid_date(d)})
    following=next((d for d in days if d>date),None)
    if date not in days or not following:raise ValueError('缺少下一交易日历，不能形成入场计划')
    next_open=datetime.strptime(following,'%Y%m%d').replace(hour=9,minute=30,tzinfo=ZONE)
    if next_open-close>timedelta(days=31):raise ValueError('下一交易日历距离异常')
    records={};unavailable=[];generated=[]
    for strategy,h in heads.items():
        raw=checked_file(root,root/'releases'/generation/strategy/'report.json',MAX_REPORT).read_bytes()
        if len(raw)!=h['report_bytes'] or hashlib.sha256(raw).hexdigest()!=h['report_sha256']:raise ValueError('精选报告校验失败')
        r=json.loads(raw)
        if (r.get('schema_version')!=1 or r.get('strategy_id')!=strategy or r.get('as_of')!=date or r.get('data_revision')!=info['data_revision']):raise ValueError('精选报告身份不符')
        observed=datetime.fromisoformat(r['generated_at'])
        if observed.tzinfo is None or observed<close:raise ValueError('报告尚未收盘')
        generated.append(observed.timestamp())
        stocks=r['stocks']
        if not isinstance(stocks,list) or len(stocks)!=h['stock_count'] or len({s['ts_code'] for s in stocks})!=len(stocks):raise ValueError('精选股票集合无效')
        picks=[s for s in stocks if s.get('state')=='入选']
        if type(r.get('shortlist_count')) is not int or len(picks)!=r['shortlist_count'] or len(picks)>10:raise ValueError('精选数量无效')
        if strategy=='orderflow' and (r.get('orderflow_status') or {}).get('status')!='complete':
            if picks:raise ValueError('未完成策略携带精选')
            unavailable.append(strategy);continue
        ranks=sorted(s.get('rank') for s in picks)
        if ranks!=list(range(1,len(picks)+1)):raise ValueError('精选排名无效')
        for stock in picks:
            code=stock['ts_code']
            if (not re.fullmatch(r'\d{6}\.(SH|SZ)',code) or stock.get('trade_date')!=date or stock.get('stale') is not False
                    or not isinstance(stock.get('name'),str) or not stock['name'] or len(stock['name'])>30
                    or not finite(stock.get('close')) or stock['close']<=0 or not finite(stock.get('change'))):raise ValueError('精选报价无效')
            metrics={k:stock[k] for k in METRICS if k in stock and finite(stock[k])}
            evidence=dict(strategy=strategy,name=r.get('strategy_name',strategy),description=DESCRIPTIONS[strategy],
                metrics=metrics,checks={k:stock.get(k) for k in ['trend_ok','strength_ok','pullback_ok','volume_ok','turn_ok'] if type(stock.get(k)) is bool})
            pending=['下一交易日开盘价、停牌及封板状态尚需核验','公告、财务与真实成交条件尚未完整核查']
            if stock.get('adjusted') is not True or stock.get('limit_available') is not True:pending.append('本日复权因子或涨跌停价缺失')
            if code not in records:
                records[code]=dict(ts_code=code,name=stock['name'],price=stock['close'],change=stock['change'],quote_at=close.timestamp(),
                    price_date=date,quote_basis='daily_close',strategies=[],strategy_evidence=[],checks=[],pending=[],input_conflict=False)
            row=records[code]
            if row['price']!=stock['close'] or row['change']!=stock['change']:raise ValueError('跨策略收盘价冲突')
            row['data_incomplete']=row.get('data_incomplete',False) or stock.get('adjusted') is not True or stock.get('limit_available') is not True
            row['strategies'].append(strategy);row['strategy_evidence'].append(evidence);row['pending']=sorted(set(row['pending']+pending))
    state=dict(info,source_generated_at=max(generated),plan_expires_at=next_open.timestamp(),next_session=following,
        unavailable_strategies=unavailable,candidates=[records[c] for c in sorted(records)],
        units=dict(price='CNY closing price',change='percent points',atr='ATR/price fraction',ret20='fraction',amount20='thousand CNY',score='strategy-specific matching score, NOT probability; not comparable across strategies'),
        horizon='Next trading session entry PLAN; observe 1-5 trading days. Next open must be checked again; skip gap above 3%, suspension or locked limit-up.',
        limitation='Only dated post-close technical evidence. No verified news, fundamentals, portfolio or next-open execution data. Do not infer extra facts from stock names.')
    if len(state['candidates'])>50 or len(json.dumps(state,ensure_ascii=False).encode())>60000:raise ValueError('盘后JEV输入超过上限')
    return state


def result_path(store,generation):
    if not isinstance(generation,str) or not GENERATION.fullmatch(generation):raise ValueError('版本无效')
    return store.root/'jev-daily'/(generation+'.json')


def read_daily(store,generation):
    root=store.root.parent.parent;heads=headers(root,generation);info=identity(heads)
    try:r=load_record(store.root,result_path(store,generation))
    except (OSError,ValueError):
        return dict(info,schema_version=1,status='pending' if store.settings().get('jev_enabled') else 'disabled',input_sha256='',rows=[],message='等待盘后JEV分析' if store.settings().get('jev_enabled') else '请先启用JEV判断')
    if any(r.get(k)!=info[k] for k in ['generation','data_revision','source_report_shas']):raise ValueError('JEV结果与精选版本不符')
    r=copy.deepcopy(r);superseded=current_generation(root)!=generation
    if r.get('status') in ['pending','running','waiting_input'] and not store.settings().get('jev_enabled'):
        r.update(status='cancelled',rows=[],message='JEV已停用')
    for row in r.get('rows',[]):row['expired']=row.get('historical',False) or superseded or store.clock()>=row['expires_at']
    return r


def request_daily(store,generation):
    root=store.root.parent.parent;info=identity(headers(root,generation))
    with store.lock():
        cfg=store.settings()
        if not cfg.get('jev_enabled') or not cfg.get('jev_key'):raise ValueError('请先配置JEV')
        if current_generation(root)!=generation:raise ValueError('请先同步最新精选版本')
        path=result_path(store,generation)
        if path.exists():
            try:old=load_record(store.root,path)
            except (OSError,ValueError):old={}
            if store.clock()-old.get('requested_at',0)<60:raise BlockingIOError('请稍后重试')
        save(path,dict(info,schema_version=1,status='pending',input_sha256='',rows=[],message='等待盘后JEV分析',
             request_id=str(uuid.uuid4()),requested_at=store.clock(),manual=True,config_generation=cfg.get('jev_generation')))
    return {'status':'pending','generation':generation}


def process_daily(store,transport=call_api):
    root=store.root.parent.parent
    try:generation=current_generation(root);info=identity(headers(root,generation))
    except (OSError,ValueError,KeyError,TypeError):return
    path=result_path(store,generation)
    with store.lock():
        cfg=store.settings();key=cfg.get('jev_key')
        if not cfg.get('jev_enabled') or not key:return
        old=None
        if path.exists():
            try:old=load_record(store.root,path)
            except (OSError,ValueError):return  # Explicit retry can replace a corrupt sidecar.
            if old.get('status')=='running' and store.clock()-old.get('started_at',0)>=60:
                old.update(status='unavailable',rows=[],message='上次盘后JEV中断，可手动重试');save(path,old);return
            if old.get('status') not in ['pending','waiting_input']:return
            if old.get('status')=='waiting_input' and store.clock()<old.get('retry_at',0):return
            if old.get('config_generation')!=cfg.get('jev_generation'):
                old.update(status='cancelled',rows=[],message='JEV配置已改变，旧请求已取消');save(path,old);return
        request_id=old['request_id'] if old else str(uuid.uuid4())
    try:state=load_input(root,generation,store.calendar())
    except (OSError,ValueError,KeyError,TypeError):
        with store.lock():
            current=store.settings()
            if not current.get('jev_enabled') or current.get('jev_generation')!=cfg.get('jev_generation'):return
            if path.exists():
                try:present=load_record(store.root,path)
                except (OSError,ValueError):return
                if old is None or present.get('request_id')!=request_id or present.get('status') not in ['pending','waiting_input']:return
            save(path,dict(info,schema_version=1,status='waiting_input',input_sha256='',rows=[],
                message='精选或交易日历尚未通过校验，等待重试；未调用JEV',request_id=request_id,
                requested_at=old['requested_at'] if old else store.clock(),manual=bool(old and old.get('manual')),
                retry_at=store.clock()+60,config_generation=cfg.get('jev_generation')))
        return
    with store.lock():
        current=store.settings()
        if current_generation(root)!=generation or current.get('jev_generation')!=cfg.get('jev_generation') or not current.get('jev_enabled'):return
        if path.exists():
            present=load_record(store.root,path)
            if old is None or present.get('request_id')!=request_id or present.get('status') not in ['pending','waiting_input']:return
        target=dict(info,schema_version=1,status='running',input_sha256=digest(state),rows=[],message='正在分析盘后精选',
                    request_id=request_id,requested_at=old['requested_at'] if old else store.clock(),started_at=store.clock(),config_generation=cfg.get('jev_generation'))
        if not state['candidates'] or not (old and old.get('manual')) and store.clock()>=state['plan_expires_at']:
            target.update(status='empty' if not state['candidates'] else 'expired',message='本版没有完整策略的精选候选' if not state['candidates'] else '本版计划时段已结束，可手动回看');save(path,target);return
        save(path,target)
    try:
        payload=request_payload(state)
        with dispatch_lock(store.root):
            with store.lock():
                current=store.settings()
                if (not current.get('jev_enabled') or current.get('jev_key')!=key or current.get('jev_generation')!=target['config_generation']
                        or current_generation(root)!=generation):raise ValueError('配置或精选版本已改变')
            raw=transport(key,payload)
        result=decode(raw,state,store.clock())
        result.update(info,request_id=request_id,requested_at=target['requested_at'],config_generation=target['config_generation'],unavailable_strategies=state['unavailable_strategies'])
    except Exception:result=dict(target,status='unavailable',rows=[],message='盘后JEV暂未完成，原精选保持不变；可手动重试')
    with store.lock():
        current=store.settings()
        if load_record(store.root,path).get('request_id')!=request_id:return
        if not current.get('jev_enabled') or current.get('jev_generation')!=target['config_generation']:
            result=dict(target,status='cancelled',rows=[],message='JEV配置已改变，本次分析取消')
        attempt=store.root/'jev-daily/attempts'/(request_id+'.json')
        if attempt.exists():raise ValueError('JEV判断版本不可改写')
        save(attempt,result);save(path,result);prune(path.parent,1000);prune(attempt.parent,1000)
