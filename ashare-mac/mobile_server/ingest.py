"""Extract only allowlisted files and validate the complete market/research bundle."""
import hashlib
import json
import os
import shutil
import stat
import tempfile
import time
import zipfile
from pathlib import Path,PurePosixPath
from deployment.publish import verify,publish as publish_market
from engine.snapshot_protocol import FILE_NAMES,REVISION,sha256_file
from engine.close_proof import valid_date,verify_package_close
from .artifacts import STRATEGIES,GENERATION,CODE,MAX_REPORT,MAX_CHART,checked_file,atomic_json
from .queue import PERSISTENT_FIELDS,CONTEXT_FIELDS


def member_limit(name):
    parts=PurePosixPath(name).parts
    if '\\' in name or name.startswith('/') or '..' in parts or '' in parts:raise ValueError('Unsafe archive name')
    if name=='bundle.json' or name=='market/manifest.json':return 65536
    if len(parts)==3 and parts[:2]==('market','raw') and parts[2] in FILE_NAMES:return 512*1024*1024
    if len(parts)==3 and parts[0]=='research' and parts[1] in STRATEGIES and parts[2] in ['report.json','manifest.json']:
        return MAX_REPORT if parts[2]=='report.json' else 65536
    if len(parts)==3 and parts[:2]==('research','charts') and parts[2].endswith('.json') and CODE.fullmatch(parts[2][:-5]):return MAX_CHART
    raise ValueError('Unexpected archive entry')


def extract(bundle,destination):
    with zipfile.ZipFile(bundle) as archive:
        members=archive.infolist();names=[m.filename for m in members]
        if len(members)>11000 or len(set(names))!=len(names) or sum(m.file_size for m in members)>512*1024*1024:raise ValueError('Archive limits exceeded')
        for entry in members:
            mode=entry.external_attr>>16
            if entry.is_dir() or stat.S_ISLNK(mode) or entry.flag_bits&1 or entry.file_size>member_limit(entry.filename):raise ValueError('Unsafe archive entry')
            target=destination/entry.filename;target.parent.mkdir(parents=True,exist_ok=True)
            with archive.open(entry) as source,target.open('xb') as output:
                remaining=entry.file_size
                while remaining:
                    data=source.read(min(1024*1024,remaining))
                    if not data:raise ValueError('Incomplete archive entry')
                    output.write(data);remaining-=len(data)
                if source.read(1):raise ValueError('Archive size mismatch')
    metadata=json.loads(checked_file(destination,destination/'bundle.json',65536).read_text())
    base={'schema_version','input_revision','data_revision','generation'}
    closing={'expected_as_of','close_attestation'}
    if set(metadata) not in [base,base|closing] or metadata['schema_version']!=1 or not all(REVISION.fullmatch(metadata[k]) for k in ['input_revision','data_revision']) or not GENERATION.fullmatch(metadata['generation']):raise ValueError('Invalid bundle metadata')
    market=verify(destination/'market',metadata['data_revision'])
    if closing.issubset(metadata):
        if not valid_date(metadata['expected_as_of']):raise ValueError('Invalid expected closing date')
        verify_package_close(destination/'market',metadata['expected_as_of'],metadata['close_attestation'])
    codes=None
    for strategy in STRATEGIES:
        folder=destination/'research'/strategy
        info=json.loads(checked_file(destination,folder/'manifest.json',65536).read_text())
        report_bytes=checked_file(destination,folder/'report.json',MAX_REPORT).read_bytes()
        report=json.loads(report_bytes)
        if (info.get('schema_version')!=1 or info.get('generation')!=metadata['generation'] or info.get('strategy')!=strategy
                or info.get('data_revision')!=market['revision'] or info.get('as_of')!=market['as_of']
                or info.get('report_bytes')!=len(report_bytes) or info.get('report_sha256')!=hashlib.sha256(report_bytes).hexdigest()
                or report.get('data_revision')!=market['revision'] or report.get('as_of')!=market['as_of'] or report.get('strategy_id')!=strategy):raise ValueError('Research version mismatch')
        if closing.issubset(metadata):
            refreshed=report.get('last_update') or {}
            if (refreshed.get('forced_latest_date')!=metadata['expected_as_of']
                    or refreshed.get('close_attestation')!=metadata['close_attestation']):
                raise ValueError('Research closing evidence differs from the upload proof')
        current={stock['ts_code'] for stock in report['stocks']}
        if len(current)!=info['stock_count'] or len(current)!=len(report['stocks']) or not 1<=len(current)<=10000 or not all(CODE.fullmatch(code) for code in current):raise ValueError('Invalid research stock universe')
        if codes is not None and current!=codes:raise ValueError('Research universes differ')
        codes=current
    charts=destination/'research/charts'
    if {p.name for p in charts.iterdir()}!={code+'.json' for code in codes}:raise ValueError('Missing or unexpected charts')
    for code in codes:
        candles=json.loads(checked_file(destination,charts/(code+'.json'),MAX_CHART).read_text())
        if not isinstance(candles,list) or not 1<=len(candles)<=120:raise ValueError('Invalid chart')
        dates=[bar['date'] for bar in candles]
        if dates!=sorted(set(dates)) or any(date>market['as_of'] for date in dates):raise ValueError('Invalid chart dates')
    return metadata


def activate(bundle,root,market_root,queue,job):
    stage=Path(tempfile.mkdtemp(prefix='ingest-',dir=root/'work')).resolve()
    market_stage=None
    try:
        with queue.locked():
            captured=queue.state()
            if captured['status']!='publishing' or not queue.owns(captured,job['id'],job['lease']):raise ValueError('Expired publication lease')
        # Copy into the publisher's 0700 work directory before hashing/extracting.
        # The API account cannot alter this copy even if an upload response is lost.
        immutable=stage/'processing.zip'
        checked_file(root/'incoming',bundle,256*1024*1024)
        with bundle.open('rb') as source,immutable.open('xb') as output:
            remaining=captured['artifact_bytes']
            while remaining:
                chunk=source.read(min(1024*1024,remaining))
                if not chunk:raise ValueError('Incomplete upload')
                output.write(chunk);remaining-=len(chunk)
            if source.read(1):raise ValueError('Upload exceeds declared size')
        if sha256_file(immutable)!=captured['artifact_sha256']:raise ValueError('Upload checksum mismatch')
        metadata=extract(immutable,stage)
        if metadata.get('expected_as_of')!=captured.get('expected_as_of'):
            raise ValueError('Closing job target or fresh-data proof is missing from upload')
        # systemd exposes the two writable roots as separate bind mounts.
        # Copy into private market staging, then rename on that same mount.
        market_stage=Path(tempfile.mkdtemp(prefix='.mobile-',dir=market_root/'staging'))
        shutil.copytree(stage/'market',market_stage,dirs_exist_ok=True)
        with queue.locked():
            state=queue.state()
            if (state['status']!='publishing' or not queue.owns(state,job['id'],job['lease'])
                    or any(state.get(k)!=captured.get(k) for k in {'artifact_bytes','artifact_sha256'}|CONTEXT_FIELDS)):raise ValueError('Publication identity changed')
            current=json.loads((market_root/'current/manifest.json').read_text())['revision']
            if current not in [metadata['input_revision'],metadata['data_revision']]:raise ValueError('Market snapshot changed during computation')
            target=market_root/'staging'/metadata['data_revision']
            if target.exists():raise ValueError('Market staging is busy')
            os.rename(market_stage,target)
            try:publish_market(market_root,metadata['data_revision'])
            finally:
                if target.exists():shutil.rmtree(target)
            release=root/'releases'/metadata['generation'];release.parent.mkdir(exist_ok=True)
            if release.exists():raise ValueError('Research generation already exists')
            for path in (stage/'research').rglob('*'):path.chmod(0o750 if path.is_dir() else 0o640)
            (stage/'research').chmod(0o750);os.rename(stage/'research',release)
            old=(root/'current').resolve() if (root/'current').is_symlink() else None
            pointer=root/('.current-'+os.urandom(4).hex());pointer.symlink_to(Path('releases')/metadata['generation']);os.replace(pointer,root/'current')
            if old and old.is_dir() and old!=release:os.utime(old,None)
            state={k:v for k,v in state.items() if k in PERSISTENT_FIELDS|{'executor'}}
            state.update(status='completed',message='已发布 '+metadata['data_revision'][:8]+f' · {len(STRATEGIES)} 套盘后策略及 K 线校验通过');queue.save(state)
        if metadata.get('expected_as_of'):
            atomic_json(root/'jobs/closing-receipts'/(metadata['expected_as_of']+'.json'),
                {'schema_version':1,'date':metadata['expected_as_of'],'generation':metadata['generation'],
                 'data_revision':metadata['data_revision'],'close_attestation':metadata['close_attestation'],
                 'job_id':captured['id'],'published_at':time.time()})
        versions=sorted([p for p in (root/'releases').iterdir() if GENERATION.fullmatch(p.name) and p.is_dir() and not p.is_symlink()],key=lambda p:p.stat().st_mtime,reverse=True)
        protected={metadata['generation'],*[p.name for p in versions if p!=release][:2]}
        for path in versions:
            if path.name not in protected and time.time()-path.stat().st_mtime>86400:shutil.rmtree(path)
        return metadata
    finally:
        if market_stage is not None and market_stage.exists():shutil.rmtree(market_stage)
        shutil.rmtree(stage)
