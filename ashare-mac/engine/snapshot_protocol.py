"""Versioned, bounded transport contract for the five public market tables."""
import hashlib
import json
import re
import os
import shutil
import time
from datetime import datetime

FILE_NAMES=('daily.parquet','adj_factor.parquet','stk_limit.parquet','stock_basic.parquet','trade_cal.parquet')
REVISION=re.compile(r'^\d{8}-[a-f0-9]{16}$')
MAX_FILE_BYTES=512*1024*1024


def revision_for(value):
    payload={k:value[k] for k in ['schema_version','as_of','files']}
    encoded=json.dumps(payload,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
    return value['as_of']+'-'+hashlib.sha256(encoded).hexdigest()[:16]


def validate_manifest(value):
    try:
        if value['schema_version']!=1 or not REVISION.fullmatch(value['revision']): raise ValueError()
        datetime.strptime(value['as_of'],'%Y%m%d')
        files=value['files']
        if len(files)!=len(FILE_NAMES) or {f['name'] for f in files}!=set(FILE_NAMES): raise ValueError()
        for f in files:
            if (type(f['bytes']) is not int or not 0<f['bytes']<=MAX_FILE_BYTES
                    or type(f['rows']) is not int or f['rows']<=0
                    or not re.fullmatch(r'[a-f0-9]{64}',f['sha256'])): raise ValueError()
        if sum(f['bytes'] for f in files)>1024*1024*1024: raise ValueError()
        if value['revision']!=revision_for(value): raise ValueError()
    except (KeyError,TypeError,ValueError,AttributeError):
        raise ValueError('服务器数据清单无效或校验不一致') from None
    return value


def sha256_file(path):
    digest=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''): digest.update(chunk)
    return digest.hexdigest()


def prune_snapshots(directory,current,previous=None,now=None,keep=3,grace_seconds=86400):
    """Caller holds its publication lock. Keep rollback versions and in-flight readers.

    Grace starts when a version leaves current, not when it was created. Unknown
    directories and symlinks are never removed. Untracked versions get a full grace.
    """
    now=time.time() if now is None else now
    if not REVISION.fullmatch(current) or keep<1:raise ValueError('Invalid retention policy')
    directory=directory.resolve();retired=directory/'.retired'
    if retired.is_symlink():raise ValueError('Unsafe retirement directory')
    retired.mkdir(mode=0o700,exist_ok=True)
    active_marker=retired/current
    if active_marker.is_symlink():raise ValueError('Unsafe retirement marker')
    if active_marker.exists():active_marker.unlink()
    versions=[]
    for path in directory.iterdir():
        if not REVISION.fullmatch(path.name) or path.is_symlink() or not path.is_dir():continue
        manifest=path/'manifest.json'
        if manifest.is_symlink() or not manifest.is_file() or manifest.stat().st_size>65536:continue
        try:value=validate_manifest(json.loads(manifest.read_text()))
        except (ValueError,OSError):continue
        if value['revision']!=path.name or path.name==current:continue
        marker=retired/path.name
        if marker.is_symlink():continue
        if not marker.exists():
            marker.touch(mode=0o600,exist_ok=False);os.utime(marker,(now,now))
        elif path.name==previous:os.utime(marker,(now,now),follow_symlinks=False)
        versions.append((marker.stat().st_mtime,path.stat().st_mtime,path.name,path,marker))
    versions.sort(reverse=True)
    removed=[]
    for retired_at,_,name,path,marker in versions[max(0,keep-1):]:
        if now-retired_at<grace_seconds:continue
        shutil.rmtree(path);marker.unlink();removed.append(name)
    return removed


def retain_snapshots(directory,current,previous=None):
    # A housekeeping error must never invalidate an already verified activation.
    try:
        removed=prune_snapshots(directory,current,previous)
        if removed:print(f'已清理 {len(removed)} 个过期行情版本',flush=True)
    except (OSError,ValueError):
        print('行情版本已保存；旧版本清理未完成，请检查目录权限和磁盘空间',flush=True)
