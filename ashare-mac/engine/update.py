"""Incrementally complete the latest 120 market sessions through ProMax."""
import argparse
import os
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import fcntl

import pandas as pd

from .data import FIELDS, atomic_json, publish_day, read_dataset
from .provider import ProMax


def status(text: str) -> None:
    print(text, flush=True)


def save_reference(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.pending.parquet')
    frame.to_parquet(temporary, index=False)
    pd.testing.assert_frame_equal(frame, pd.read_parquet(temporary))
    os.replace(temporary, path)


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
        calendar = client.fetch('trade_cal', exchange='SSE', start_date=f'{int(cutoff[:4])-1}0101', end_date=f'{cutoff[:4]}1231')
        if not {'cal_date', 'is_open', 'exchange'}.issubset(calendar.columns) or calendar.empty:
            raise ValueError('交易日历缺失')
        if not calendar.exchange.eq('SSE').all() or not calendar.is_open.isin([0, 1]).all():
            raise ValueError('交易日历字段无效')
        pd.to_datetime(calendar.cal_date, format='%Y%m%d', errors='raise')
        if str(calendar.cal_date.max()) < cutoff:
            raise ValueError('交易日历未覆盖目标日期')
        save_reference(overlay/'reference'/'trade_cal.parquet', calendar)
        dates = sorted(calendar.loc[(calendar.is_open == 1) & (calendar.cal_date <= cutoff), 'cal_date'].astype(str))[-120:]
        if not dates:
            raise ValueError('找不到已收盘的交易日')
        status('读取本地覆盖范围…')
        datasets = {k: read_dataset(root, overlay, k) for k in FIELDS}
        by_day = {k: {d: g for d, g in f.groupby('trade_date')} for k, f in datasets.items()}
        needed = []
        for date in dates:
            frames = {k: by_day[k].get(date) for k in FIELDS}
            daily = frames['daily']
            complete = daily is not None and len(daily) >= 4000
            codes = set(daily.ts_code) if daily is not None else set()
            for k in ['adj_factor', 'stk_limit']:
                f = frames[k]
                complete = complete and f is not None and len(codes & set(f.ts_code)) >= len(codes)*(1 if k == 'adj_factor' else .99)
            if not complete:
                needed.append(date)
        failures, published = [], 0
        for i, date in enumerate(needed):
            try:
                frames = {}
                for k in FIELDS:
                    local = by_day[k].get(date)
                    daily = by_day['daily'].get(date)
                    coverage = (len(set(local.ts_code) & set(daily.ts_code))/len(daily)
                                if local is not None and daily is not None and len(daily) else 0)
                    sufficient = local is not None and (len(local) >= 4000 if k == 'daily' else coverage >= (1 if k == 'adj_factor' else .99))
                    if sufficient:
                        frames[k] = local
                    else:
                        status(f'补齐 {i+1}/{len(needed)} · {date} · {k}')
                        remote = client.fetch(k, trade_date=date, fields=','.join(FIELDS[k]))
                        if k == 'daily' and len(remote) < 4000:
                            raise ValueError('日线不足 4000 行，保留旧数据')
                        frames[k] = remote
                publish_day(overlay/'updates', date, frames)
                published += 1
                status(f'已校验并保存 {date} · {len(frames["daily"])} 只')
            except ValueError as e:
                failures.append({'date':date, 'error':str(e)})
                status(f'{date} 暂未补齐：{e}')
                if len(failures)>=3 and all('HTTP' in f['error'] or '网络' in f['error'] for f in failures[-3:]):
                    break
        status('更新股票名称与行业…')
        basic = client.fetch('stock_basic', list_status='L', fields='ts_code,symbol,name,industry,market,list_date,list_status')
        required = ['ts_code', 'name', 'industry', 'list_date']
        if len(basic) < 4000 or not set(required).issubset(basic.columns) or basic[['ts_code', 'name', 'list_date']].isna().any().any():
            raise ValueError('股票列表不完整，保留旧列表')
        pd.to_datetime(basic.list_date, format='%Y%m%d', errors='raise')
        save_reference(overlay/'reference'/'stock_basic.parquet', basic)
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
