"""Read-only local sources and validated, immutable update partitions."""
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

KEYS = ['ts_code', 'trade_date']
FIELDS = {
    'daily': KEYS + ['open', 'high', 'low', 'close', 'pre_close', 'vol', 'amount'],
    'adj_factor': KEYS + ['adj_factor'],
    'stk_limit': KEYS + ['up_limit', 'down_limit'],
}


def validate(frame: pd.DataFrame, kind: str) -> pd.DataFrame:
    columns = FIELDS[kind]
    if not set(columns).issubset(frame.columns) or frame.empty:
        raise ValueError(f'{kind}: 空数据或缺少必要字段')
    x = frame[columns].copy()
    if x[KEYS].isna().any().any():
        raise ValueError(f'{kind}: 主键缺失')
    for key in KEYS:
        x[key] = x[key].astype(str)
    if not x.ts_code.str.fullmatch(r'\d{6}\.(SH|SZ|BJ)').all():
        raise ValueError(f'{kind}: 股票代码格式错误')
    dates = x.trade_date.drop_duplicates()
    if not dates.str.fullmatch(r'\d{8}').all() or pd.to_datetime(
            dates, format='%Y%m%d', errors='coerce').isna().any():
        raise ValueError(f'{kind}: 日期格式错误')
    if x.duplicated(KEYS).any():
        raise ValueError(f'{kind}: 重复主键')
    numeric = columns[2:]
    for col in numeric:
        x[col] = pd.to_numeric(x[col], errors='raise').astype(float)
    if not np.isfinite(x[numeric].to_numpy()).all():
        raise ValueError(f'{kind}: 数值缺失或非有限数')
    if kind == 'daily':
        bad = ((x[['open', 'high', 'low', 'close', 'pre_close']] <= 0).any(axis=1)
               | (x[['vol', 'amount']] < 0).any(axis=1)
               | (x.high + 1e-6 < x[['open', 'low', 'close']].max(axis=1))
               | (x.low - 1e-6 > x[['open', 'high', 'close']].min(axis=1)))
    elif kind == 'adj_factor':
        bad = x.adj_factor <= 0
    else:
        bad = (x.down_limit < 0) | (x.up_limit < x.down_limit)
    if bad.any():
        raise ValueError(f'{kind}: {int(bad.sum())} 行价格或成交数据无效')
    return x


def combine(frames: List[pd.DataFrame], kind: str) -> pd.DataFrame:
    if not frames:
        return pd.DataFrame(columns=FIELDS[kind])
    x = pd.concat([validate(f, kind) for f in frames if not f.empty], ignore_index=True)
    duplicates = x[x.duplicated(KEYS, keep=False)].copy()
    if len(duplicates):
        for col in FIELDS[kind][2:]:
            duplicates[col] = duplicates[col].round(6)
        if duplicates.drop_duplicates().duplicated(KEYS).any():
            raise ValueError(f'{kind}: 不同来源有冲突行情，停止合并')
    return x.drop_duplicates(KEYS).sort_values(KEYS).reset_index(drop=True)


def source_paths(root: Path, overlay: Path, kind: str) -> List[Path]:
    paths = [root/'raw'/f'{kind}.parquet']
    if kind == 'daily':
        paths += sorted(p for p in (root/'refreshes').glob('*/daily_*.parquet')
                        if not p.name.startswith('daily_basic'))
    paths += sorted((overlay/'updates').glob(f'[0-9]*/{kind}.parquet'))
    return list(dict.fromkeys(p.resolve() for p in paths if p.is_file()))


def read_dataset(root: Path, overlay: Path, kind: str) -> pd.DataFrame:
    return combine([pd.read_parquet(p, columns=FIELDS[kind])
                    for p in source_paths(root, overlay, kind)], kind)


def read_reference(root: Path, overlay: Path, kind: str) -> pd.DataFrame:
    new = overlay/'reference'/f'{kind}.parquet'
    return pd.read_parquet(new if new.exists() else root/'raw'/f'{kind}.parquet')


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.json-')
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(value, f, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
            f.flush(); os.fsync(f.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def publish_day(root: Path, date: str, frames: Dict[str, pd.DataFrame]) -> None:
    if not pd.Series([date]).str.fullmatch(r'\d{8}').all():
        raise ValueError('非法更新日期')
    checked = {k: validate(frames[k], k) for k in FIELDS}
    for kind, frame in checked.items():
        if set(frame.trade_date) != {date}:
            raise ValueError(f'{kind}: 返回日期与请求不一致')
    codes = set(checked['daily'].ts_code)
    for kind in ['adj_factor', 'stk_limit']:
        coverage = len(codes & set(checked[kind].ts_code)) / len(codes)
        if coverage < (1.0 if kind == 'adj_factor' else 0.99):
            raise ValueError(f'{kind}: 跨表覆盖不足 {coverage:.1%}')
    root.mkdir(parents=True, exist_ok=True)
    target = root/date
    if target.exists():
        # Published days are immutable; a retry is safe only if identical.
        for k, f in checked.items():
            combine([pd.read_parquet(target/f'{k}.parquet'), f], k)
        return
    stage = Path(tempfile.mkdtemp(prefix='.staging-', dir=root))
    try:
        for kind, frame in checked.items():
            file = stage/f'{kind}.parquet'
            frame.to_parquet(file, index=False)
            pd.testing.assert_frame_equal(frame.reset_index(drop=True), pd.read_parquet(file))
        atomic_json(stage/'metadata.json', {'date': date, 'provider': 'promax',
                    'rows': {k: len(v) for k, v in checked.items()}, 'validation': 'ok'})
        os.rename(stage, target)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
