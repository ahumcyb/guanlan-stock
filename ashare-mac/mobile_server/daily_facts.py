"""Deterministic close facts from a verified, fixed market/research generation."""
import hashlib
import json
import math
from datetime import datetime
from pathlib import Path
from engine.close_proof import valid_date, verify_package_close, ZONE
from engine.snapshot_protocol import REVISION
from .artifacts import STRATEGIES, HISTORICAL_STRATEGIES, GENERATION, MAX_REPORT, checked_file


def evidence_hash(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,allow_nan=False,
                                   separators=(',',':')).encode()).hexdigest()


def short_text(value, maximum):
    value='' if value is None else str(value)
    return ''.join(c for c in value if ord(c)>=32).strip()[:maximum]


def finite(value):
    return type(value) in (int,float) and math.isfinite(value)


def collect_evidence(root, market_current, date, now):
    import pandas as pd
    if not valid_date(date):raise ValueError('复盘日期无效')
    root=Path(root).resolve();receipt_root=root/'jobs/closing-receipts'
    receipt=json.loads(checked_file(receipt_root,receipt_root/(date+'.json'),65536).read_text())
    generation=receipt.get('generation','');revision=receipt.get('data_revision','')
    if (receipt.get('schema_version')!=1 or receipt.get('date')!=date
            or not GENERATION.fullmatch(generation) or not REVISION.fullmatch(revision)):
        raise ValueError('复盘发布凭据无效')
    research=root/'releases'/generation
    market=Path(market_current).parent.resolve()/'releases'/revision
    if any(p.is_symlink() or p.resolve()!=p or not p.is_dir() for p in [research,market]):
        raise ValueError('复盘绑定的数据版本暂不可用')
    header=json.loads(checked_file(market,market/'manifest.json',65536).read_text())
    if header.get('revision')!=revision:raise ValueError('复盘行情版本不一致')
    frames=verify_package_close(market,date,receipt.get('close_attestation'),datetime.fromtimestamp(now,ZONE))
    from .daily_performance import collect_previous_performance
    from .daily_changes import market_changes,selection_changes,removal_reason
    performance=collect_previous_performance(root,market,date,frames)
    prior_codes={group['id']:{row['ts_code'] for row in group['rows']} for group in performance.get('strategies',[])}
    reviews={}
    quotes=frames['daily'].set_index('ts_code')
    daily_codes=set(frames['daily'].ts_code);universe=None;strategies=[];breadth=None;metadata_warning=False
    ids=STRATEGIES if (research/'left_rebound/manifest.json').exists() else HISTORICAL_STRATEGIES
    for strategy in ids:
        folder=research/strategy
        manifest=json.loads(checked_file(research,folder/'manifest.json',65536).read_text())
        raw=checked_file(research,folder/'report.json',MAX_REPORT).read_bytes()
        if (manifest.get('generation')!=generation or manifest.get('data_revision')!=revision
                or manifest.get('as_of')!=date or manifest.get('strategy')!=strategy
                or manifest.get('report_bytes')!=len(raw)
                or manifest.get('report_sha256')!=hashlib.sha256(raw).hexdigest()):
            raise ValueError('复盘策略文件校验失败')
        report=json.loads(raw);stocks=report.get('stocks',[])
        if not isinstance(stocks,list) or not 1<=len(stocks)<=10000:raise ValueError('复盘股票集合无效')
        codes={row.get('ts_code') for row in stocks}
        if (report.get('as_of')!=date or report.get('strategy_id')!=strategy or report.get('data_revision')!=revision
                or len(codes)!=len(stocks) or len(stocks)!=manifest.get('stock_count')
                or not daily_codes.issubset(codes) or universe is not None and codes!=universe):
            raise ValueError('四策略与当日行情未对齐')
        universe=codes
        update=report.get('last_update') or {}
        if update.get('close_attestation')!=receipt['close_attestation'] or update.get('forced_latest_date')!=date:
            raise ValueError('策略缺少相同的收盘核验记录')
        metadata_warning |= any(item.get('date')=='stock_basic' for item in update.get('failures',[]))
        picks=[]
        for stock in stocks:
            if stock.get('state')!='入选':continue
            if (stock.get('trade_date')!=date or stock.get('ts_code') not in daily_codes
                    or any(not finite(stock.get(k)) for k in ['close','change','score','rank'])):
                raise ValueError('复盘候选不是有效的当日结果')
            quote=quotes.loc[stock['ts_code']]
            if (type(stock['rank']) is not int or not 0<=stock['score']<=100
                    or abs(stock['close']-quote.close)>1e-6
                    or abs(stock['change']-(quote.close/quote.pre_close-1)*100)>1e-4):
                raise ValueError('复盘候选价格与当日行情不一致')
            picks.append(dict(ts_code=stock['ts_code'],name=short_text(stock.get('name'),30),
                industry=short_text(stock.get('industry'),40),close=stock['close'],change=stock['change'],
                score=stock['score'],rank=stock['rank']))
        if len(picks)!=report.get('shortlist_count') or len(picks)>10:raise ValueError('复盘候选数量不一致')
        picks.sort(key=lambda row:row['rank'])
        if [p['rank'] for p in picks]!=list(range(1,len(picks)+1)):raise ValueError('复盘候选排名无效')
        for name in ['confirmed_count','watching_count']:
            if type(report.get(name)) is not int or not 0<=report[name]<=10000:raise ValueError('复盘策略计数无效')
        if report['confirmed_count']<len(picks):raise ValueError('复盘确认数量不足')
        threshold=report.get('market_filter_threshold',None if strategy=='momentum_60' else .4)
        reviews[strategy]={stock['ts_code']:removal_reason(stock,date,quotes.loc[stock['ts_code']] if stock['ts_code'] in daily_codes else None,
            threshold,report.get('breadth',0)) for stock in stocks if stock['ts_code'] in prior_codes.get(strategy,set())}
        strategies.append(dict(id=strategy,name=short_text(report.get('strategy_name'),40),
            shortlist_count=len(picks),confirmed_count=report['confirmed_count'],watching_count=report['watching_count'],picks=picks,
            market_filter_applies=threshold is not None,market_filter_threshold=threshold,
            market_filter_passed=(report.get('breadth',0)>=threshold) if threshold is not None else None))
        if strategy=='leaders':breadth=report.get('breadth')
        del report,stocks,raw
    if not finite(breadth) or not 0<=breadth<=1:raise ValueError('市场宽度无效')
    prices=frames['daily']
    prices=prices[prices.ts_code.str.fullmatch(r'(00|30)\d{4}\.SZ|(60|68)\d{4}\.SH')].copy()
    if len(prices)<4000:raise ValueError('沪深收盘样本不足')
    prices['change']=(prices.close/prices.pre_close-1)*100
    limits=frames['stk_limit'][['ts_code','up_limit','down_limit']]
    prices=prices.merge(limits,on='ts_code',how='left',validate='one_to_one')
    known=prices.up_limit.gt(prices.down_limit) & prices.down_limit.ge(0)
    market_stats=dict(stock_count=len(prices),advancers=int((prices.change>1e-8).sum()),
        decliners=int((prices.change < -1e-8).sum()),unchanged=int((prices.change.abs()<=1e-8).sum()),
        turnover_yi=round(float(prices.amount.sum()/100000),2),
        median_change=round(float(prices.change.median()),4),
        limit_up=int((known & (prices.close>=prices.up_limit-.001)).sum()),
        limit_down=int((known & (prices.close<=prices.down_limit+.001)).sum()),
        limits_unclassified=int((~known).sum()),breadth=float(breadth))
    sectors=[];warnings=[]
    if not metadata_warning:
        basic=pd.read_parquet(market/'raw/stock_basic.parquet',columns=['ts_code','industry'])
        if basic.ts_code.duplicated().any():raise ValueError('行业映射存在重复代码')
        prices=prices.merge(basic,on='ts_code',how='left',validate='one_to_one')
        prices['industry']=prices.industry.fillna('未分类').map(lambda v:short_text(v,40))
        for name,group in prices.groupby('industry'):
            if name in ['', '未分类'] or len(group)<5:continue
            sectors.append(dict(name=name,members=len(group),mean_change=round(float(group.change.mean()),4),
                                turnover_yi=round(float(group.amount.sum()/100000),2)))
    else:
        warnings.append('股票名称与行业资料更新未完成，本期不做行业排序；候选名称沿用缓存资料。')
    if market_stats['limits_unclassified']:
        warnings.append('涨跌停仅按有效限制价统计，未设限或缺失限制价的股票不纳入。')
    from .selection_snapshots import save_snapshot
    try:save_snapshot(root,date,generation,revision,strategies,receipt.get('published_at'))
    except (OSError,ValueError,KeyError,TypeError):
        warnings.append('本日精选快照未能冻结，后续结算须等待可验证的历史版本。')
    strong=sorted(sectors,key=lambda x:(-x['mean_change'],x['name']))[:5]
    return dict(date=date,generation=generation,data_revision=revision,
        fetched_at=receipt['close_attestation']['fetched_at'],
        universe_label='沪深 A 股个股日线，含 ST；不含 ETF、北交所和指数',
        market=market_stats,sectors_strong=strong,
        sectors_weak=sorted(sectors,key=lambda x:(x['mean_change'],x['name']))[:5],
        strategies=strategies,performance=performance,warnings=warnings,
        market_changes=market_changes(root,performance.get('signal_date'),market_stats,strong),
        selection_changes=selection_changes(strategies,performance,reviews))
