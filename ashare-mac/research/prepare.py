"""Verify immutable inputs and create a causal feature/selection panel, without P&L."""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import numpy as np
import pandas as pd
from engine.data import FIELDS, full_market_dates, validate, atomic_json
from .acquire import check_limits, check_status
from .signals import make_signals


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def load_constraints(cache, revision, daily, dates):
    info=json.loads((cache/'manifest.json').read_text())
    if not info['complete'] or info['failures'] or info['source_revision']!=revision or info['dates']!=dates:
        raise ValueError('Research constraint manifest is incomplete or mismatched')
    expected={f'limits/{d}.parquet' for d in dates}|{f'status/{d[:6]}.parquet' for d in dates}
    if {f['path'] for f in info['files']}!=expected or len(info['files'])!=len(expected):
        raise ValueError('Research partition set mismatch')
    limit_frames=[];status_frames=[]
    codes={d:set(g.ts_code) for d,g in daily.groupby('trade_date') if d in dates}
    for meta in info['files']:
        name=meta['path']
        if not re.fullmatch(r'(limits/\d{8}|status/\d{6})\.parquet',name):raise ValueError('Invalid research partition path')
        path=cache/name
        if path.is_symlink() or path.stat().st_size!=meta['bytes'] or sha(path)!=meta['sha256']:
            raise ValueError('Research partition checksum mismatch')
        x=pd.read_parquet(path)
        if len(x)!=meta['rows']:raise ValueError('Research row count mismatch')
        if name.startswith('limits/'):
            limit_frames.append(check_limits(x,path.stem,codes[path.stem]))
        else:
            status_frames.append(check_status(x,[d for d in dates if d.startswith(path.stem)]))
    return pd.concat(limit_frames,ignore_index=True),pd.concat(status_frames,ignore_index=True)


def prepare(root, constraints, output):
    config=json.loads(Path(__file__).with_name('protocol.json').read_text())
    manifest=json.loads((root/'manifest.json').read_text())
    if manifest['revision']!=config['data_revision']:raise ValueError('Wrong market source revision')
    for item in manifest['files']:
        if sha(root/'raw'/item['name'])!=item['sha256']:raise ValueError('Raw market checksum mismatch')
    daily=validate(pd.read_parquet(root/'raw/daily.parquet'), 'daily')
    factors=validate(pd.read_parquet(root/'raw/adj_factor.parquet'), 'adj_factor')
    full=full_market_dates(daily.groupby('trade_date').size().sort_index())
    calendar=pd.read_parquet(root/'raw/trade_cal.parquet')
    dates=sorted(calendar.loc[(calendar.is_open==1)&calendar.cal_date.between(full[0],full[-1]),'cal_date'].unique())
    research_dates=[d for d in dates if config['train'][0]<=d<=config['holdout'][1]]
    recent=daily.loc[daily.trade_date.isin(full)]
    main=recent.loc[recent.ts_code.str.fullmatch(r'(00\d{4}\.SZ|60\d{4}\.SH)')]
    limits,status=load_constraints(constraints,manifest['revision'],main,research_dates)
    print('Verified raw and constraint hashes; computing causal signals without strategy returns',flush=True)
    panel=make_signals(main,factors,limits,status,dates,research_dates,
                       config['positions'],config['liquidity_fraction'])
    etf=recent.loc[recent.ts_code=='510300.SH'].merge(factors,on=['ts_code','trade_date'],validate='one_to_one').set_index('trade_date').reindex(dates)
    for key,column in [('etf_open','open'),('etf_close','close'),('etf_factor','adj_factor')]:panel[key]=etf[column].to_numpy()
    output.parent.mkdir(parents=True,exist_ok=True)
    temporary=output.with_name('.panel.pending.npz');np.savez_compressed(temporary,**panel)
    with np.load(temporary,allow_pickle=False) as checked:
        if checked['open'].shape!=(len(dates),len(panel['codes'])):raise ValueError('Panel readback failed')
    os.replace(temporary,output)
    code_files=['research/signals.py','research/prepare.py','research/acquire.py','engine/strategy.py','engine/golden_pit.py','engine/data.py']
    app=Path(__file__).resolve().parents[1]
    atomic_json(output.with_suffix('.json'),{'data_revision':manifest['revision'],
        'constraint_manifest_sha256':sha(constraints/'manifest.json'),'panel_sha256':sha(output),
        'code':{f:sha(app/f) for f in code_files},'protocol_sha256':sha(Path(__file__).with_name('protocol.json')),
        'dates':len(dates),'stocks':len(panel['codes']),'research_dates':len(research_dates),
        'pandas':pd.__version__,'numpy':np.__version__})
    print(f'Causal panel saved: {len(dates)} sessions, {len(panel["codes"])} historical main-board codes',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--constraints',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();prepare(args.root.resolve(),args.constraints.resolve(),args.output.resolve())
