"""Incrementally complete the latest 120 market sessions through ProMax."""
import argparse
import os
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor, as_completed
import fcntl

import pandas as pd

from .data import FIELDS, atomic_json, publish_day, read_dataset, read_reference, full_market_dates, minimum_market_rows
from .provider import ProMax


def status(text: str) -> None:
    print(text, flush=True)


def save_reference(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.pending.parquet')
    frame.to_parquet(temporary, index=False)
    pd.testing.assert_frame_equal(frame, pd.read_parquet(temporary))
    os.replace(temporary, path)


def validate_reference(basic, previous):
    required=['ts_code','name','industry','list_date']
    if not set(required).issubset(basic.columns) or basic[['ts_code','name','list_date']].isna().any().any():
        raise ValueError('股票列表缺少必要字段，保留旧列表')
    prior_codes=set(previous.ts_code) if not previous.empty else set()
    if len(basic)<max(4000,len(prior_codes)*.97) or (prior_codes and len(set(basic.ts_code)&prior_codes)<len(prior_codes)*.97):
        raise ValueError('股票列表覆盖不足历史基准的 97%，保留旧列表')
    if basic.ts_code.duplicated().any() or not basic.ts_code.str.fullmatch(r'\d{6}\.(SH|SZ|BJ)').all():
        raise ValueError('股票列表主键无效')
    normalized=basic.copy()
    normalized['list_date']=pd.to_datetime(basic.list_date.astype('string'),format='%Y%m%d',errors='raise').dt.strftime('%Y%m%d')
    return normalized


def validate_calendar(calendar, start, end):
    required={'cal_date','is_open','exchange'}
    if not required.issubset(calendar.columns) or calendar.empty:
        raise ValueError('交易日历缺失')
    expected=set(pd.date_range(start,end).strftime('%Y%m%d'))
    if (not calendar.exchange.eq('SSE').all() or not calendar.is_open.isin([0,1]).all()
            or calendar.cal_date.duplicated().any() or set(calendar.cal_date)!=expected):
        raise ValueError('交易日历日期不连续或字段无效，保留旧日历')


def load_calendar(root,overlay,start,end,client):
    for path in [overlay/'reference'/'trade_cal.parquet',root/'raw'/'trade_cal.parquet']:
        if not path.exists(): continue
        try:
            table=pd.read_parquet(path)
            table=table.loc[(table.exchange=='SSE') & table.cal_date.between(start,end),
                            ['exchange','cal_date','is_open']].drop_duplicates().reset_index(drop=True)
            validate_calendar(table,start,end)
            status('本地交易日历完整，复用已校验日历')
            return table
        except (ValueError,KeyError,AttributeError):
            continue
    table=pd.concat([
        client.fetch('trade_cal',exchange='SSE',start_date=start,end_date=end,is_open=value)
        for value in (1,0)
    ],ignore_index=True).drop_duplicates().reset_index(drop=True)
    validate_calendar(table,start,end)
    return table


def update(root: Path, overlay: Path, through=None) -> dict:
    root, overlay = root.resolve(), overlay.resolve()
    if root == overlay or root in overlay.parents or overlay in root.parents:
        raise ValueError('补充数据目录必须与原始数据目录分离')
    overlay.mkdir(parents=True, exist_ok=True)
    with (overlay/'.update.lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('已有数据更新正在运行') from None
        client = ProMax()
        now = datetime.now(ZoneInfo('Asia/Shanghai'))
        cutoff = through or (now if now.hour >= 18 else now-timedelta(days=1)).strftime('%Y%m%d')
        pd.to_datetime(cutoff, format='%Y%m%d', errors='raise')
        status('连接 ProMax，核对交易日历…')
        cal_start,cal_end=f'{int(cutoff[:4])-1}0101',f'{cutoff[:4]}1231'
        calendar=load_calendar(root,overlay,cal_start,cal_end,client)
        save_reference(overlay/'reference'/'trade_cal.parquet', calendar)
        dates = sorted(calendar.loc[(calendar.is_open == 1) & (calendar.cal_date <= cutoff), 'cal_date'].astype(str))[-120:]
        if not dates:
            raise ValueError('找不到已收盘的交易日')
        status('读取本地覆盖范围…')
        datasets = {k: read_dataset(root, overlay, k) for k in FIELDS}
        by_day = {k: {d: g for d, g in f.groupby('trade_date')} for k, f in datasets.items()}
        known_counts=datasets['daily'].groupby('trade_date').size().sort_index()
        complete_dates=set(full_market_dates(known_counts))
        needed = []
        for date in dates:
            frames = {k: by_day[k].get(date) for k in FIELDS}
            daily = frames['daily']
            complete = daily is not None and date in complete_dates
            codes = set(daily.ts_code) if daily is not None else set()
            for k in ['adj_factor', 'stk_limit']:
                f = frames[k]
                complete = complete and f is not None and len(codes & set(f.ts_code)) >= len(codes)*(1 if k == 'adj_factor' else .99)
            if not complete:
                needed.append(date)
        failures, published = [], 0

        def complete_day(i, date):
            try:
                frames = {}
                for k in FIELDS:
                    local = by_day[k].get(date)
                    daily = by_day['daily'].get(date)
                    coverage = (len(set(local.ts_code) & set(daily.ts_code))/len(daily)
                                if local is not None and daily is not None and len(daily) else 0)
                    sufficient = local is not None and (date in complete_dates if k == 'daily' else coverage >= (1 if k == 'adj_factor' else .99))
                    if sufficient:
                        frames[k] = local
                    else:
                        status(f'补齐 {i+1}/{len(needed)} · {date} · {k}')
                        # This ProMax deployment's fields-filtered historical pages
                        # were observed to overlap; request defaults and project
                        # canonical columns in validate() after completeness checks.
                        remote = client.fetch(k, trade_date=date)
                        minimum=minimum_market_rows(known_counts,date)
                        if k == 'daily' and len(remote) < minimum:
                            raise ValueError(f'日线仅 {len(remote)} 行，低于近期覆盖阈值 {minimum}，保留旧数据')
                        frames[k] = remote
                publish_day(overlay/'updates', date, frames)
                status(f'已校验并保存 {date} · {len(frames["daily"])} 只')
                return None
            except ValueError as e:
                status(f'{date} 暂未补齐：{e}')
                return {'date':date, 'error':str(e)}

        # Independent immutable day partitions; at most three in-flight requests.
        with ThreadPoolExecutor(max_workers=3) as workers:
            futures=[workers.submit(complete_day,i,d) for i,d in enumerate(needed)]
            for future in as_completed(futures):
                failure=future.result()
                if failure: failures.append(failure)
                else: published+=1
        failures.sort(key=lambda f:f['date'])
        status('更新股票名称与行业…')
        try:
            basic = client.fetch('stock_basic', list_status='L')
            try: previous=read_reference(root,overlay,'stock_basic')
            except FileNotFoundError: previous=pd.DataFrame()
            basic=validate_reference(basic,previous)
            save_reference(overlay/'reference'/'stock_basic.parquet', basic)
        except ValueError as e:
            failures.append({'date':'stock_basic','error':str(e)})
            status(f'股票列表保留本地版本：{e}')
        result = {'through': dates[-1], 'updated_days': published, 'checked_sessions': len(dates),
                  'completed_at': now.isoformat(), 'provider': 'ProMax',
                  'validation': 'partial' if failures else 'ok', 'failures':failures}
        atomic_json(overlay/'last_update.json', result)
        status(f'更新结束 · 目标 {dates[-1]} · 已补齐 {published} 日 · 未补齐 {len(failures)} 日')
        return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-root', type=Path, required=True)
    parser.add_argument('--overlay', type=Path, required=True)
    parser.add_argument('--through')
    args = parser.parse_args()
    try:
        update(args.data_root, args.overlay, args.through)
    except Exception as e:
        # Never print a provider payload or traceback with transport internals.
        print(str(e) if isinstance(e, ValueError) else f'更新失败（{type(e).__name__}），原有数据已保留', flush=True)
        raise SystemExit(1)
