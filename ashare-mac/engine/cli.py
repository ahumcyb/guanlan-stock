"""Reproducible JSON/CSV reports, published as an atomic generation."""
import argparse
import fcntl
import hashlib
import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from .data import read_dataset, read_reference, source_paths, atomic_json, full_market_dates
from .strategy import VERSION, STRATEGIES, features, classify, select_day
from .backtest import study
from .snapshot_protocol import validate_manifest,sha256_file


def immutable_revision(root,overlay):
    path=root/'manifest.json'
    if not path.is_file():return None
    for kind in ['daily','adj_factor','stk_limit']:
        if source_paths(root,overlay,kind)!=[root/'raw'/(kind+'.parquet')]:return None
    if any((overlay/'reference'/name).exists() for name in ['stock_basic.parquet','trade_cal.parquet']):return None
    manifest=validate_manifest(json.loads(path.read_text()))
    for entry in manifest['files']:
        data=root/'raw'/entry['name']
        if data.stat().st_size!=entry['bytes'] or sha256_file(data)!=entry['sha256']:raise ValueError('不可变行情版本校验失败')
    return manifest['revision']


def progress(message):
    print(message, flush=True)


def records(frame):
    return json.loads(frame.replace([np.inf,-np.inf], np.nan).to_json(orient='records', double_precision=6))


def write_charts(signals,codes,stage,asof,data_revision):
    """Write one shared chart set for the requested codes only."""
    chart_cols = ['trade_date','adj_open','adj_high','adj_low','price','ma10','ma20','ma60','vol']
    from .chart_data import make_extended, write_extended
    (stage/'charts').mkdir(exist_ok=True)
    wanted=set(codes)
    tails = signals[signals.ts_code.isin(wanted)].groupby('ts_code',sort=False).tail(500) if wanted else signals.iloc[0:0]
    for code, group in tails.groupby('ts_code',sort=False):
        chart = group.tail(120)[chart_cols].copy()
        scale = float(group.close.iloc[-1])/group.price.iloc[-1]
        for c in chart_cols[1:-1]: chart[c] *= scale
        chart.columns = ['date','open','high','low','close','ma10','ma20','ma60','volume']
        (stage/'charts'/f'{code}.json').write_text(json.dumps(records(chart),separators=(',',':')),encoding='utf-8')
        write_extended(stage/'charts-extended'/f'{code}.json.gz',make_extended(group,code,asof,data_revision))


LIST_FIELDS=('ts_code','name','industry','trade_date','close','change','score','state','rank',
             'eligible','stale','adjusted','limit_available','amount20',
             'trend_ok','strength_ok','pullback_ok','volume_ok','turn_ok')
WATCH_STATES=frozenset({'入选','等待','观察','转强','符合'})


def list_stock(stock):
    return stock if stock.get('state')=='入选' else {key:stock[key] for key in LIST_FIELDS if key in stock}


def generate(root: Path, overlay: Path, output: Path, strategy='leaders', charts='priority'):
    root, overlay, output = root.resolve(), overlay.resolve(), output.resolve()
    if charts not in ['none','priority','all']:raise ValueError('未知 K 线生成范围')
    if output == root or output in root.parents or root in output.parents:
        raise ValueError('报告输出目录必须与行情源目录分离')
    output.mkdir(parents=True, exist_ok=True)
    with (output/'.build.lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('已有选股计算正在运行') from None
        progress('读取并校验本地日线、复权因子和涨跌停价…')
        data_revision=immutable_revision(root,overlay)
        daily = read_dataset(root, overlay, 'daily')
        if daily.empty:
            raise ValueError('找不到日线，请选择包含 raw/daily.parquet 的数据目录')
        factors = read_dataset(root, overlay, 'adj_factor')
        limits = read_dataset(root, overlay, 'stk_limit')
        basic = read_reference(root, overlay, 'stock_basic')
        calendar = read_reference(root, overlay, 'trade_cal')
        counts = daily.groupby('trade_date').size()
        full = counts.loc[full_market_dates(counts)]
        if full.empty:
            raise ValueError('不足以构建全市场截面（至少 4000 只有效日线）')
        asof = str(full.index.max())
        recent = daily[daily.trade_date.isin(full.index)]
        bars = recent.merge(basic[['ts_code','name','industry','list_date']], on='ts_code', how='left', validate='many_to_one')
        market_dates = sorted(calendar.loc[(calendar.is_open==1) & (calendar.cal_date<=asof)
                                           & (calendar.cal_date>=str(full.index.min())), 'cal_date'].astype(str).unique().tolist())
        if not set(recent.trade_date.unique()).issubset(market_dates):
            raise ValueError('日线与交易日历不一致')
        progress(f'计算 {bars.ts_code.nunique():,} 只股票的趋势、量能与风险…')
        computed = features(bars,market_dates=market_dates)
        if strategy in ['momentum_60','left_rebound','orderflow']:
            from .momentum import add_constraints
            computed = add_constraints(computed, factors, limits)
        signals = classify(computed,strategy=strategy)
        orderflow_status=None
        if strategy=='orderflow':
            from .orderflow import collect_daily
            progress('核验有日期的大单资金流与盘口复盘…')
            signals,orderflow_status=collect_daily(signals,asof,market_dates)
        del computed
        latest = signals[signals.trade_date==asof]
        shortlist = select_day(latest)
        all_latest = signals.groupby('ts_code',sort=False).tail(1).copy()
        all_latest['stale'] = all_latest.trade_date != asof
        for col in ['eligible','confirmed','watch','setup']:
            all_latest.loc[all_latest.stale, col] = False
        all_latest.loc[all_latest.stale, 'score'] = 0.
        all_latest['name'] = all_latest.name.fillna(all_latest.ts_code)
        all_latest['industry'] = all_latest.industry.fillna('未分类')
        all_latest['state'] = np.select([all_latest.ts_code.isin(shortlist.ts_code),all_latest.confirmed,
            all_latest.watch,all_latest.eligible], ['入选','符合' if strategy in ['momentum_60','left_rebound'] else '转强','等待','观察'],default='排除')
        all_latest['change'] = all_latest.ret1 * 100
        all_latest['rank'] = all_latest.ts_code.map({c:i+1 for i,c in enumerate(shortlist.ts_code)}).fillna(0).astype(int)
        all_latest['adjusted'] = all_latest.ts_code.isin(factors.loc[factors.trade_date==asof,'ts_code'])
        all_latest['limit_available'] = all_latest.ts_code.isin(limits.loc[limits.trade_date==asof,'ts_code'])
        keep = ['ts_code','name','industry','trade_date','close','change','score','state','rank','eligible','stale',
                'adjusted','limit_available','ret20','rs20','atr','volume_ratio','pullback','extension','amount20',
                'support','breakout','invalidation','trend_ok','strength_ok','pullback_ok','volume_ok','turn_ok',
                'strength_score','trend_score','position_score','volume_score','risk_score','liquidity_rank']
        if strategy == 'golden_pit':
            from .golden_pit import METRICS
            keep += METRICS
        if strategy == 'momentum_60':
            from .momentum import METRICS
            keep += METRICS
        if strategy == 'left_rebound':
            from .left_rebound import METRICS
            keep += METRICS
        if strategy=='orderflow':
            from .orderflow import METRICS
            keep += METRICS
        stocks = all_latest[keep].sort_values(['score','ts_code'],ascending=[False,True])
        progress('检验 1 / 3 / 5 日信号：次日开盘、真实涨跌停价、成本压力…')
        backtest = (dict(start='',end=asof,horizons=[],monthly=[],events=[],benchmark_label='大单历史数据尚未建立可验证样本，不展示代理回测')
                    if strategy=='orderflow' else study(signals, factors, limits, market_dates))
        now = datetime.now(ZoneInfo('Asia/Shanghai'))
        from .market_clock import market_status
        opened=calendar.loc[calendar.is_open==1,'cal_date'].astype(str).tolist()
        expected_as_of=market_status(opened,now)['expected_as_of']
        stale_sessions=sum(asof<d<=expected_as_of for d in opened) if expected_as_of else 0
        missing_adj = len(set(latest.ts_code)-set(factors.loc[factors.trade_date==asof,'ts_code']))
        missing_limit = len(set(latest.ts_code)-set(limits.loc[limits.trade_date==asof,'ts_code']))
        warnings = ['历史股票名单与 ST 状态缺少逐日快照，存在幸存者偏差；当前行业也用于历史分组。',
                    '固定参数的历史信号研究，样本会重叠；尚未完成独立样本外与模拟实盘验证。',
                    '按日线与实际限制价估计成交，未建模盘口、最小佣金与整数手数；不构成组合收益。']
        if strategy=='orderflow':
            warnings=[orderflow_status['message'],'新研究策略：仅使用有源日期的资金流与盘口价格、累计量；D3缺失时用达塔完整分钟路径复核；大额成交接口缺交易日期，暂未纳入。','资金流是供应商按成交规模分类的估算，不代表机构身份；尚无独立样本外盈利验证。','限定日线初筛后成交额前200只，缺数时不出精选；从发布日起积累真实候选，不以日线代理补造历史胜率。']
        if strategy == 'momentum_60':
            warnings[0] = '此处历史事件按当前股票名称过滤，存在名单与 ST 状态回溯偏差；本策略不设行业限额。'
            warnings.insert(0, '新增研究策略：2026 年 1–4 月选择期资金账本胜率 48.69%，净收益 +1.99%；开发期净收益 -6.34%，尚未通过完整验证。此页全期事件统计属于事后观察，不能替代封存研究。')
        if strategy == 'left_rebound':
            warnings.insert(0,'左侧观察：超跌与抛压收敛不代表底部已确认；固定规则尚未通过独立样本外与模拟实盘验证。')
        if missing_adj: warnings.insert(0,f'最新日线有 {missing_adj} 只缺复权因子；连续价格信号仅供观察。')
        if missing_limit: warnings.insert(0,f'最新日线有 {missing_limit} 只缺涨跌停价；缺失事件不能计为可成交。')
        if stale_sessions: warnings.insert(0,f'行情落后交易日历 {stale_sessions} 个交易日，请更新数据。')
        incomplete=counts[(counts.index>=full.index.min()) & ~counts.index.isin(full.index)].index.tolist()
        if incomplete: warnings.insert(0,'以下日期截面覆盖不足，已从信号计算排除：'+', '.join(incomplete))
        update_file = overlay/'last_update.json'
        last_update = json.loads(update_file.read_text()) if update_file.exists() else None
        if last_update and last_update.get('reference_warning'):
            warnings.insert(0,last_update['reference_warning'])
        if last_update and last_update.get('failures'):
            warnings.insert(0, '上次行情更新仍有缺口：'+', '.join(f['date'] for f in last_update['failures']))
        breadth = float(latest.breadth.iloc[0])
        sources = []
        for kind in ['daily','adj_factor','stk_limit']:
            paths = source_paths(root,overlay,kind)
            dataset = {'daily': daily, 'adj_factor': factors, 'stk_limit':limits}[kind]
            sources.append(dict(kind=kind,rows=len(dataset),files=len(paths),
                start=str(dataset.trade_date.min()) if len(dataset) else '',
                end=str(dataset.trade_date.max()) if len(dataset) else ''))
        from .strategy import MARKET_THRESHOLDS
        report = dict(schema_version=1, version=VERSION, as_of=asof, generated_at=now.isoformat(),
            strategy_id=strategy,strategy_name=STRATEGIES[strategy],data_revision=data_revision,
            market_filter_threshold=MARKET_THRESHOLDS[strategy],
            source_root=str(root), overlay_root=str(overlay), price_rows=len(daily),
            universe_count=len(latest), eligible_count=int(latest.eligible.sum()),
            confirmed_count=int(latest.confirmed.sum()), shortlist_count=len(shortlist),
            watching_count=int(latest.watch.sum()), breadth=breadth,
            regime='防守' if breadth<.4 else ('谨慎' if breadth<.6 else '积极'),
            stale_sessions=stale_sessions, missing_adjustment_today=missing_adj, missing_limits_today=missing_limit,
            sources=sources, warnings=warnings, stocks=records(stocks), backtest=backtest,
            last_update=last_update,orderflow_status=orderflow_status)
        generation = now.strftime('%Y%m%dT%H%M%S')+'-'+os.urandom(3).hex()
        stage = output/('.staging-'+generation)
        stage.mkdir()
        try:
            progress('生成研究报告、条件明细和可导出的选股表…')
            details=stage/'details';details.mkdir()
            full_rows=records(stocks)
            for row in full_rows:
                code=row['ts_code']
                (details/f'{code}.json').write_text(json.dumps(row,ensure_ascii=False,allow_nan=False,separators=(',',':')),encoding='utf-8')
            list_rows=[list_stock(row) for row in full_rows]
            report['stocks']=list_rows
            if charts!='none':
                progress('按数据版本写入共用 K 线…')
                chart_codes=sorted({row['ts_code'] for row in full_rows if charts=='all' or row.get('state') in WATCH_STATES})
                write_charts(signals,chart_codes,stage,asof,data_revision)
            else:(stage/'charts').mkdir(exist_ok=True)
            atomic_json(stage/'report.json',report)
            csv = stocks[stocks.state=='入选'].sort_values('rank').copy()
            csv.rename(columns={'ts_code':'代码','name':'名称','industry':'行业','trade_date':'信号日期',
                                'close':'收盘价','score':'匹配分','state':'状态','rank':'排名'}).to_csv(stage/'candidates.csv',index=False,encoding='utf-8-sig')
            pd.DataFrame(backtest['events']).to_csv(stage/'events.csv',index=False,encoding='utf-8-sig')
            readback = json.loads((stage/'report.json').read_text())
            if len(readback['stocks']) != len(list_rows) or readback['as_of'] != asof:
                raise ValueError('报告读回校验失败')
            if any(set(row)-set(LIST_FIELDS) for row in list_rows if row.get('state')!='入选'):
                raise ValueError('短列表字段校验失败')
            destination = output/generation
            stage.rename(destination)
            atomic_json(output/'current.json',dict(generation=generation, as_of=asof,
                sha256=hashlib.sha256((destination/'report.json').read_bytes()).hexdigest()))
        finally:
            if stage.exists(): shutil.rmtree(stage)
        progress(f'完成 · {asof} · {len(shortlist)} 只入选 · {len(stocks):,} 只可检索')
        return report


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--data-root',type=Path,required=True)
    parser.add_argument('--overlay',type=Path,default=Path(__file__).resolve().parents[1]/'data')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--strategy',choices=STRATEGIES,default='leaders')
    parser.add_argument('--charts',choices=['none','priority','all'],default='priority')
    a=parser.parse_args()
    try: generate(a.data_root,a.overlay,a.output,a.strategy,a.charts)
    except Exception as e:
        print(str(e) if isinstance(e,ValueError) else f'计算失败（{type(e).__name__}），旧报告已保留',flush=True)
        raise SystemExit(1)
