import hashlib
import json
import os
import re
import shutil
import time
from pathlib import Path
from engine.snapshot_protocol import REVISION

PREVIOUS_STRATEGIES=('leaders','pullback','golden_pit','left_rebound')
STRATEGIES=(*PREVIOUS_STRATEGIES,'orderflow')
HISTORICAL_STRATEGIES=('leaders','pullback','golden_pit','momentum_60')
SUPPORTED_STRATEGIES=(*STRATEGIES,'momentum_60')
LIST_FIELDS=('ts_code','name','industry','trade_date','close','change','score','state','rank',
             'eligible','stale','adjusted','limit_available','amount20')
WATCH_STATES=frozenset({'入选','等待','观察','转强','符合'})


def valid_strategy_group(ids):
    return len(ids)==len(set(ids)) and set(ids) in (set(STRATEGIES),set(PREVIOUS_STRATEGIES),set(HISTORICAL_STRATEGIES))

def published_strategies(folder):
    if (folder/'orderflow/manifest.json').exists():return STRATEGIES
    return PREVIOUS_STRATEGIES if (folder/'left_rebound/manifest.json').exists() else HISTORICAL_STRATEGIES
GENERATION=re.compile(r'^\d{8}T\d{6}-[a-f0-9]{6}$')
CODE=re.compile(r'^\d{6}\.(SH|SZ|BJ)$')
MAX_REPORT=12*1024*1024
MAX_CHART=128*1024
MAX_DETAIL=65536


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


def list_stock(stock):
    return {key:stock[key] for key in LIST_FIELDS if key in stock}


def priority_chart_codes(*reports,extra=()):
    codes=set(extra)
    for report in reports:
        for stock in report.get('stocks',[]):
            if stock.get('state') in WATCH_STATES and CODE.fullmatch(stock.get('ts_code','')):
                codes.add(stock['ts_code'])
    return codes


def preserved_legacy_generations(releases):
    """Retain the last verified report and shared charts for retired clients."""
    releases=releases.resolve();preserved=set()
    for strategy in set(SUPPORTED_STRATEGIES)-set(STRATEGIES):
        for folder in sorted(releases.iterdir(),key=lambda p:p.name,reverse=True):
            if not GENERATION.fullmatch(folder.name) or folder.is_symlink() or not folder.is_dir():continue
            try:
                manifest=json.loads(checked_file(releases,folder/strategy/'manifest.json',65536).read_text())
                data=checked_file(releases,folder/strategy/'report.json',MAX_REPORT).read_bytes()
                report=json.loads(data)
                if (manifest['strategy']!=strategy or manifest['generation']!=folder.name
                        or manifest['report_bytes']!=len(data)
                        or manifest['report_sha256']!=hashlib.sha256(data).hexdigest()
                        or report['strategy_id']!=strategy):continue
                preserved.add(folder.name);break
            except (OSError,ValueError,KeyError,TypeError):continue
    return preserved


def _copy_shared_charts(stage,chart_root,extended_root,codes,asof,data_revision):
    """Copy one shared chart set. Missing codes are skipped for on-demand generation."""
    from engine.chart_data import read_extended,MAX_COMPRESSED
    chart_root=Path(chart_root);has_extended=extended_root is not None and Path(extended_root).is_dir()
    if has_extended:(stage/'charts-extended').mkdir(exist_ok=True)
    (stage/'charts').mkdir(exist_ok=True)
    copied=0
    for code in sorted(codes):
        source=chart_root/(code+'.json')
        if not source.is_file() or source.is_symlink():continue
        source=checked_file(chart_root,source,MAX_CHART)
        candles=json.loads(source.read_text())
        if not isinstance(candles,list) or not 1<=len(candles)<=120:raise ValueError('Invalid chart')
        shutil.copyfile(source,stage/'charts'/(code+'.json'));copied+=1
        if has_extended:
            packed=Path(extended_root)/(code+'.json.gz')
            if not packed.is_file() or packed.is_symlink():continue
            packed=checked_file(extended_root,packed,MAX_COMPRESSED)
            read_extended(packed,code,asof,data_revision,candles)
            shutil.copyfile(packed,stage/'charts-extended'/(code+'.json.gz'))
    return copied


def publish(outputs,root,data_revision,strategies=None,charts_root=None,chart_codes=None):
    """Publish strategies with one shared chart set and one atomic pointer change."""
    if not REVISION.fullmatch(data_revision):raise ValueError('Invalid market revision')
    strategies=tuple(strategies or STRATEGIES)
    if not valid_strategy_group(strategies):raise ValueError('Invalid strategy group')
    root=root.resolve();releases=root/'releases';releases.mkdir(parents=True,exist_ok=True)
    generation=time.strftime('%Y%m%dT%H%M%S')+'-'+os.urandom(3).hex()
    stage=releases/('.staging-'+generation);stage.mkdir()
    try:
        manifests={};codes=None;asof=None;source_root=None;reports=[]
        shared_charts=Path(charts_root) if charts_root else None
        for strategy in strategies:
            folder,report=read_generation(outputs/strategy)
            current_codes={s['ts_code'] for s in report['stocks']}
            if (report['schema_version']!=1 or report['strategy_id']!=strategy or report.get('data_revision')!=data_revision
                    or not all(CODE.fullmatch(c) for c in current_codes)
                    or len(current_codes)!=len(report['stocks']) or not 1<=len(current_codes)<=10000):
                raise ValueError('Invalid research report')
            if asof and (report['as_of']!=asof or current_codes!=codes or report['source_root']!=source_root):raise ValueError('Strategy snapshots are not aligned')
            asof=report['as_of'];codes=current_codes;source_root=report['source_root']
            if shared_charts is None:shared_charts=folder/'charts'
            reports.append(report)
            report=dict(report)
            report['source_root']='行情服务器';report['overlay_root']='行情服务器'
            report['backtest']=dict(report.get('backtest') or {});report['backtest'].pop('events',None)
            # Publish the short list only; full condition rows stay under details/.
            details=folder/'details'
            destination=stage/strategy;destination.mkdir()
            if details.is_dir() and not details.is_symlink():
                (destination/'details').mkdir()
                for path in details.iterdir():
                    if path.suffix=='.json' and CODE.fullmatch(path.stem) and path.is_file() and not path.is_symlink():
                        checked_file(details,path,MAX_DETAIL)
                        shutil.copyfile(path,destination/'details'/path.name)
            report['stocks']=[list_stock(s) for s in report['stocks']]
            atomic_json(destination/'report.json',report)
            data=(destination/'report.json').read_bytes()
            if len(data)>MAX_REPORT:raise ValueError('Report too large')
            manifests[strategy]=dict(schema_version=1,generation=generation,strategy=strategy,as_of=asof,
                report_bytes=len(data),report_sha256=hashlib.sha256(data).hexdigest(),stock_count=len(codes),data_revision=data_revision)
            atomic_json(destination/'manifest.json',manifests[strategy])
        wanted=set(chart_codes) if chart_codes is not None else priority_chart_codes(*reports)
        if not wanted:wanted=set(list(codes)[:1]) if codes else set()
        if not wanted.issubset(codes):raise ValueError('Chart codes are outside the published universe')
        extended=shared_charts.parent/'charts-extended' if shared_charts is not None else None
        if shared_charts is None or not shared_charts.is_dir():raise ValueError('Shared charts are missing')
        _copy_shared_charts(stage,shared_charts,extended if extended and extended.is_dir() else None,wanted,asof,data_revision)
        for file in stage.rglob('*'):file.chmod(0o750 if file.is_dir() else 0o640)
        stage.chmod(0o750)
        os.rename(stage,releases/generation)
        old=(root/'current').resolve() if (root/'current').is_symlink() else None
        link=root/('.current-'+os.urandom(4).hex())
        link.symlink_to(Path('releases')/generation);os.replace(link,root/'current')
        if old and old.is_dir() and old.parent==releases and old.name!=generation:
            os.utime(old,None)  # Retirement grace, not original creation age.
        versions=sorted([p for p in releases.iterdir() if GENERATION.fullmatch(p.name) and p.is_dir() and not p.is_symlink()],key=lambda p:p.stat().st_mtime,reverse=True)
        protected={generation,*[p.name for p in versions if p.name!=generation][:2]}|preserved_legacy_generations(releases)
        for version in versions:
            if version.name not in protected and time.time()-version.stat().st_mtime>86400:shutil.rmtree(version)
        return manifests
    finally:
        if stage.exists():shutil.rmtree(stage)


def patch_orderflow(output,root,generation,data_revision):
    """Attach orderflow onto an already published generation without moving the pointer."""
    if not GENERATION.fullmatch(generation):raise ValueError('Invalid generation')
    if not REVISION.fullmatch(data_revision):raise ValueError('Invalid market revision')
    root=root.resolve();release=(root/'releases'/generation).resolve()
    if release.parent!=root/'releases' or not release.is_dir() or release.is_symlink():raise ValueError('Invalid release')
    current=(root/'current').resolve(strict=True)
    if current!=release:raise ValueError('Orderflow patch must target the published generation')
    for strategy in PREVIOUS_STRATEGIES:
        if not (release/strategy/'manifest.json').is_file():raise ValueError('Base strategies are incomplete')
    folder,report=read_generation(output)
    if (report['schema_version']!=1 or report['strategy_id']!='orderflow' or report.get('data_revision')!=data_revision
            or report['as_of']!=json.loads((release/'leaders/manifest.json').read_text())['as_of']):
        raise ValueError('Invalid orderflow report')
    leaders=json.loads(checked_file(root,release/'leaders/report.json',MAX_REPORT).read_text())
    codes={s['ts_code'] for s in leaders['stocks']}
    current_codes={s['ts_code'] for s in report['stocks']}
    if current_codes!=codes:raise ValueError('Orderflow universe differs')
    stage=release/('.orderflow-'+os.urandom(4).hex());stage.mkdir()
    try:
        report=dict(report);report['source_root']='行情服务器';report['overlay_root']='行情服务器'
        report['backtest']=dict(report.get('backtest') or {});report['backtest'].pop('events',None)
        details=folder/'details'
        if details.is_dir() and not details.is_symlink():
            (stage/'details').mkdir()
            for path in details.iterdir():
                if path.suffix=='.json' and CODE.fullmatch(path.stem) and path.is_file() and not path.is_symlink():
                    checked_file(details,path,MAX_DETAIL);shutil.copyfile(path,stage/'details'/path.name)
        report['stocks']=[list_stock(s) for s in report['stocks']]
        atomic_json(stage/'report.json',report)
        data=(stage/'report.json').read_bytes()
        if len(data)>MAX_REPORT:raise ValueError('Report too large')
        manifest=dict(schema_version=1,generation=generation,strategy='orderflow',as_of=report['as_of'],
            report_bytes=len(data),report_sha256=hashlib.sha256(data).hexdigest(),stock_count=len(codes),data_revision=data_revision)
        atomic_json(stage/'manifest.json',manifest)
        for file in stage.rglob('*'):file.chmod(0o750 if file.is_dir() else 0o640)
        destination=release/'orderflow'
        if destination.exists():shutil.rmtree(destination)
        os.rename(stage,destination)
        return manifest
    finally:
        if stage.exists():shutil.rmtree(stage)


def current_manifest(root,strategy):
    if strategy not in SUPPORTED_STRATEGIES:raise ValueError('Unknown strategy')
    release=(root/'current').resolve(strict=True)
    if release.parent!=root.resolve()/'releases' or not GENERATION.fullmatch(release.name):raise ValueError('Invalid current snapshot')
    if strategy not in STRATEGIES and not (release/strategy/'manifest.json').exists():
        for generation in sorted(preserved_legacy_generations(root/'releases'),reverse=True):
            previous=root.resolve()/'releases'/generation
            if (previous/strategy/'manifest.json').is_file():release=previous;break
    return json.loads(checked_file(root,release/strategy/'manifest.json',65536).read_text())
