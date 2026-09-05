"""Forced-command SSH data gateway. Python standard library only."""
import argparse
import os
import re
import shlex
import shutil
import sys
from pathlib import Path

NAMES={'daily.parquet','adj_factor.parquet','stk_limit.parquet','stock_basic.parquet','trade_cal.parquet'}
REVISION=re.compile(r'^\d{8}-[a-f0-9]{16}$')


def resolve_request(root,command):
    root=root.resolve(strict=True); releases=root/'releases'
    args=shlex.split(command)
    if args==['manifest']:
        release=(root/'current').resolve(strict=True)
        if release.parent!=releases or not REVISION.fullmatch(release.name):raise ValueError('Denied')
        candidate=release/'manifest.json'
    elif len(args)==3 and args[0]=='file' and REVISION.fullmatch(args[1]) and args[2] in NAMES:
        release=releases/args[1]
        candidate=release/'raw'/args[2]
    else: raise ValueError('Denied')
    resolved=candidate.resolve(strict=True)
    if resolved!=candidate or not resolved.is_file() or not resolved.is_relative_to(releases):
        raise ValueError('Denied')
    if resolved.stat().st_size>(65536 if resolved.name=='manifest.json' else 512*1024*1024):
        raise ValueError('Denied')
    return resolved


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);a=p.parse_args()
    try:
        path=resolve_request(a.root,os.environ.get('SSH_ORIGINAL_COMMAND',''))
        with path.open('rb') as source:shutil.copyfileobj(source,sys.stdout.buffer,1024*1024)
    except (ValueError,OSError):
        print('Data request denied',file=sys.stderr);raise SystemExit(2)
