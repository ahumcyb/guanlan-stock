"""Build a validated standalone market snapshot; never export trading ledgers."""
import argparse
import fcntl
import json
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import pandas as pd
import pyarrow.parquet as pq

from .data import read_dataset,read_reference,full_market_dates,atomic_json,source_paths,combine,validate,FIELDS
from .snapshot_protocol import FILE_NAMES,revision_for,validate_manifest,sha256_file,retain_snapshots
from .update import validate_reference,validate_calendar


def package(root,overlay,output,closing_date=None):
    root,overlay,output=map(lambda p:p.resolve(),[root,overlay,output])
    if output==root or output in root.parents or root in output.parents:
        raise ValueError('打包目录必须与源数据目录分开')
    output.mkdir(parents=True,exist_ok=True)
    with (output/'.package.lock').open('w') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise ValueError('已有行情打包正在运行') from None
        return _package(root,overlay,output,closing_date)


def _package(root,overlay,output,closing_date=None):
    stage=Path(tempfile.mkdtemp(prefix='.staging-',dir=output))
    (stage/'raw').mkdir()
    try:
        if closing_date:
            from .close_proof import valid_date,read_closing_partition
            if not valid_date(closing_date):raise ValueError('Invalid closing date')
            closing=read_closing_partition(overlay,closing_date)
            frames={}
            for kind in FIELDS:
                previous=[validate(pd.read_parquet(path,columns=FIELDS[kind]),kind) for path in source_paths(root,overlay,kind)]
                # Only the attested target day is replaced in the NEW snapshot.
                # The old snapshot/partitions and other dates remain immutable.
                frames[kind]=combine([*[f[f.trade_date!=closing_date] for f in previous],closing[kind]],kind)
        else:
            frames={kind:read_dataset(root,overlay,kind) for kind in ['daily','adj_factor','stk_limit']}
        counts=frames['daily'].groupby('trade_date').size()
        asof=max(full_market_dates(counts))
        codes=set(frames['daily'].loc[frames['daily'].trade_date==asof,'ts_code'])
        for kind in ['adj_factor','stk_limit']:
            covered=set(frames[kind].loc[frames[kind].trade_date==asof,'ts_code'])
            if not codes.issubset(covered): raise ValueError(f'{kind}: 最新日线代码覆盖不完整')
        basic=read_reference(root,overlay,'stock_basic')
        frames['stock_basic']=validate_reference(basic,basic)[['ts_code','name','industry','list_date']+[c for c in ['float_share','shares_date'] if c in basic]].sort_values('ts_code').reset_index(drop=True)
        calendar=read_reference(root,overlay,'trade_cal')
        calendar=calendar.loc[calendar.exchange=='SSE',['exchange','cal_date','is_open']].drop_duplicates().sort_values('cal_date').reset_index(drop=True)
        validate_calendar(calendar,str(calendar.cal_date.min()),str(calendar.cal_date.max()))
        frames['trade_cal']=calendar
        files=[]
        for filename in FILE_NAMES:
            kind=filename.removesuffix('.parquet')
            frame=frames[kind]; path=stage/'raw'/filename
            frame.to_parquet(path,index=False,compression='zstd')
            if pq.read_metadata(path).num_rows!=len(frame): raise ValueError('Parquet 读回行数不一致')
            files.append(dict(name=filename,bytes=path.stat().st_size,rows=len(frame),sha256=sha256_file(path)))
            print(f'已打包 {kind} · {len(frame):,} 行',flush=True)
        value=dict(schema_version=1,as_of=asof,files=files,
                   created_at=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat())
        value['revision']=revision_for(value);validate_manifest(value)
        atomic_json(stage/'manifest.json',value)
        destination=output/value['revision']
        if destination.exists():
            existing=validate_manifest(json.loads((destination/'manifest.json').read_text()))
            if existing['files']!=files: raise ValueError('已有版本不一致')
        else: os.rename(stage,destination)
        previous=None
        if (output/'latest.json').is_file():
            previous=json.loads((output/'latest.json').read_text()).get('revision')
        atomic_json(output/'latest.json',{'revision':value['revision']})
        retain_snapshots(output,value['revision'],previous if previous!=value['revision'] else None)
        print(f'数据包完成 · {value["revision"]} · {sum(f["bytes"] for f in files)/1024/1024:.1f} MiB',flush=True)
        return destination
    finally:
        if stage.exists():shutil.rmtree(stage)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--data-root',type=Path,required=True)
    p.add_argument('--overlay',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--closing-date')
    a=p.parse_args();package(a.data_root,a.overlay,a.output,a.closing_date)
