import hashlib
import json
import os
import re
import shutil
import time
from pathlib import Path
from engine.snapshot_protocol import REVISION

STRATEGIES=('leaders','pullback','golden_pit','left_rebound')
HISTORICAL_STRATEGIES=('leaders','pullback','golden_pit','momentum_60')
SUPPORTED_STRATEGIES=(*STRATEGIES,'momentum_60')


def valid_strategy_group(ids):
    return len(ids)==4 and set(ids) in (set(STRATEGIES),set(HISTORICAL_STRATEGIES))
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


def publish(outputs,root,data_revision):
    """Publish every strategy and shared charts with one atomic pointer change."""
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
        from engine.chart_data import read_extended,MAX_COMPRESSED
        extended_sources=[folder.parent/'charts-extended' for folder in chart_sources]
        has_extended=any(folder.exists() for folder in extended_sources)
        if has_extended and not all(folder.is_dir() and not folder.is_symlink() for folder in extended_sources):
            raise ValueError('Strategy extended charts are not aligned')
        if has_extended:(stage/'charts-extended').mkdir()
        (stage/'charts').mkdir()
        for code in sorted(codes):
            source=checked_file(chart_sources[0],chart_sources[0]/(code+'.json'),MAX_CHART)
            digest=hashlib.sha256(source.read_bytes()).digest()
            for chart_root in chart_sources[1:]:
                other=checked_file(chart_root,chart_root/(code+'.json'),MAX_CHART)
                if digest!=hashlib.sha256(other.read_bytes()).digest():raise ValueError('Strategy charts do not match')
            candles=json.loads(source.read_text())
            if not isinstance(candles,list) or not 1<=len(candles)<=120:raise ValueError('Invalid chart')
            shutil.copyfile(source,stage/'charts'/(code+'.json'))
            if has_extended:
                source=checked_file(extended_sources[0],extended_sources[0]/(code+'.json.gz'),MAX_COMPRESSED)
                digest=hashlib.sha256(source.read_bytes()).digest()
                for folder in extended_sources[1:]:
                    other=checked_file(folder,folder/(code+'.json.gz'),MAX_COMPRESSED)
                    if hashlib.sha256(other.read_bytes()).digest()!=digest:raise ValueError('Extended strategy charts differ')
                read_extended(source,code,asof,data_revision,candles)
                shutil.copyfile(source,stage/'charts-extended'/(code+'.json.gz'))
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


def current_manifest(root,strategy):
    if strategy not in SUPPORTED_STRATEGIES:raise ValueError('Unknown strategy')
    release=(root/'current').resolve(strict=True)
    if release.parent!=root.resolve()/'releases' or not GENERATION.fullmatch(release.name):raise ValueError('Invalid current snapshot')
    if strategy not in STRATEGIES and not (release/strategy/'manifest.json').exists():
        for generation in sorted(preserved_legacy_generations(root/'releases'),reverse=True):
            previous=root.resolve()/'releases'/generation
            if (previous/strategy/'manifest.json').is_file():release=previous;break
    return json.loads(checked_file(root,release/strategy/'manifest.json',65536).read_text())
