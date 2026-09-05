import hashlib
import json
import os
import re
import shutil
import time
from pathlib import Path
from engine.snapshot_protocol import REVISION

STRATEGIES=('leaders','pullback')
GENERATION=re.compile(r'^\d{8}T\d{6}-[a-f0-9]{6}$')
CODE=re.compile(r'^\d{6}\.(SH|SZ|BJ)$')
MAX_REPORT=12*1024*1024
MAX_CHART=128*1024


def atomic_json(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name('.'+path.name+'-'+os.urandom(4).hex())
    try:
        temporary.write_text(json.dumps(value,ensure_ascii=False,allow_nan=False,separators=(',',':')))
        os.replace(temporary,path)
    finally:
        if temporary.exists():temporary.unlink()


def checked_file(root,path,limit):
    root=root.resolve()
    if path.is_symlink() or path.resolve()!=path or not path.is_file() or not path.is_relative_to(root):
        raise ValueError('Invalid artifact path')
    if path.stat().st_size>limit:raise ValueError('Artifact too large')
    return path


def read_generation(output):
    output=output.resolve();pointer=json.loads((output/'current.json').read_text())
    if not GENERATION.fullmatch(pointer['generation']):raise ValueError('Invalid generation')
    folder=output/pointer['generation']
    data=checked_file(output,folder/'report.json',MAX_REPORT).read_bytes()
    if hashlib.sha256(data).hexdigest()!=pointer['sha256']:raise ValueError('Report checksum mismatch')
    return folder,json.loads(data)


def publish(outputs,root,data_revision):
    """Publish BOTH strategies and shared charts with one atomic pointer change."""
    if not REVISION.fullmatch(data_revision):raise ValueError('Invalid market revision')
    root=root.resolve();releases=root/'releases';releases.mkdir(parents=True,exist_ok=True)
    generation=time.strftime('%Y%m%dT%H%M%S')+'-'+os.urandom(3).hex()
    stage=releases/('.staging-'+generation);stage.mkdir()
    try:
        manifests={};chart_sources=[];codes=None;asof=None;source_root=None
        for strategy in STRATEGIES:
            folder,report=read_generation(outputs/strategy)
            current_codes={s['ts_code'] for s in report['stocks']}
            if (report['schema_version']!=1 or report['strategy_id']!=strategy or report.get('data_revision')!=data_revision
                    or not all(CODE.fullmatch(c) for c in current_codes)
                    or len(current_codes)!=len(report['stocks']) or not 1<=len(current_codes)<=10000):
                raise ValueError('Invalid research report')
            if asof and (report['as_of']!=asof or current_codes!=codes or report['source_root']!=source_root):raise ValueError('Strategy snapshots are not aligned')
            asof=report['as_of'];codes=current_codes;source_root=report['source_root'];chart_sources.append(folder/'charts')
            report['source_root']='行情服务器';report['overlay_root']='行情服务器'
            report['backtest'].pop('events',None)
            destination=stage/strategy;destination.mkdir()
            atomic_json(destination/'report.json',report)
            data=(destination/'report.json').read_bytes()
            if len(data)>MAX_REPORT:raise ValueError('Report too large')
            manifests[strategy]=dict(schema_version=1,generation=generation,strategy=strategy,as_of=asof,
                report_bytes=len(data),report_sha256=hashlib.sha256(data).hexdigest(),stock_count=len(codes),data_revision=data_revision)
            atomic_json(destination/'manifest.json',manifests[strategy])
        (stage/'charts').mkdir()
        for code in sorted(codes):
            source=checked_file(chart_sources[0],chart_sources[0]/(code+'.json'),MAX_CHART)
            other=checked_file(chart_sources[1],chart_sources[1]/(code+'.json'),MAX_CHART)
            if hashlib.sha256(source.read_bytes()).digest()!=hashlib.sha256(other.read_bytes()).digest():raise ValueError('Strategy charts do not match')
            candles=json.loads(source.read_text())
            if not isinstance(candles,list) or not 1<=len(candles)<=120:raise ValueError('Invalid chart')
            shutil.copyfile(source,stage/'charts'/(code+'.json'))
        for file in stage.rglob('*'):file.chmod(0o750 if file.is_dir() else 0o640)
        stage.chmod(0o750)
        os.rename(stage,releases/generation)
        old=(root/'current').resolve() if (root/'current').is_symlink() else None
        link=root/('.current-'+os.urandom(4).hex())
        link.symlink_to(Path('releases')/generation);os.replace(link,root/'current')
        if old and old.is_dir() and old.parent==releases and old.name!=generation:
            os.utime(old,None)  # Retirement grace, not original creation age.
        versions=sorted([p for p in releases.iterdir() if GENERATION.fullmatch(p.name) and p.is_dir() and not p.is_symlink()],key=lambda p:p.stat().st_mtime,reverse=True)
        protected={generation,*[p.name for p in versions if p.name!=generation][:2]}
        for version in versions:
            if version.name not in protected and time.time()-version.stat().st_mtime>86400:shutil.rmtree(version)
        return manifests
    finally:
        if stage.exists():shutil.rmtree(stage)


def current_manifest(root,strategy):
    if strategy not in STRATEGIES:raise ValueError('Unknown strategy')
    release=(root/'current').resolve(strict=True)
    if release.parent!=root.resolve()/'releases' or not GENERATION.fullmatch(release.name):raise ValueError('Invalid current snapshot')
    return json.loads(checked_file(root,release/strategy/'manifest.json',65536).read_text())
