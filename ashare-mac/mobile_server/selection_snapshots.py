"""Immutable daily shortlists, including a conservative bridge for older reports."""
import hashlib
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from engine.close_proof import valid_date,ZONE
from engine.snapshot_protocol import REVISION
from .artifacts import STRATEGIES,HISTORICAL_STRATEGIES,GENERATION,MAX_REPORT,checked_file
from .daily_performance import validate_selections


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,allow_nan=False,separators=(',',':')).encode()).hexdigest()


def generation_time(generation):
    if not isinstance(generation,str) or not GENERATION.fullmatch(generation):raise ValueError('精选版本无效')
    return datetime.strptime(generation[:15],'%Y%m%dT%H%M%S').replace(tzinfo=ZONE).timestamp()


def validate_snapshot(value):
    validate_selections(value)
    generation_time(value.get('generation'))
    if not isinstance(value.get('data_revision'),str) or not REVISION.fullmatch(value['data_revision']):raise ValueError('精选数据版本无效')
    if value.get('timing_basis') not in ['closing_receipt','legacy_generation']:raise ValueError('精选时间依据无效')
    if value['timing_basis']=='closing_receipt':
        published=value.get('published_at')
        if type(published) not in [float,int] or not 0<published<1e12:raise ValueError('精选发布时间无效')
    return value


def read_snapshot(root,path):
    original=Path(root);anchor=original.resolve();path=anchor/Path(path).relative_to(original)
    envelope=json.loads(checked_file(anchor,path,128*1024).read_text())
    value=envelope['snapshot']
    if envelope.get('sha256')!=digest(value):raise ValueError('精选快照校验失败')
    return validate_snapshot(value)


def save_snapshot(root,date,generation,revision,strategies,published_at=None):
    root=Path(root).resolve()
    value=dict(date=date,generation=generation,data_revision=revision,
        timing_basis='closing_receipt' if published_at is not None else 'legacy_generation',
        published_at=published_at,strategies=[dict(id=row['id'],name=row['name'],picks=[
            {key:pick[key] for key in ['ts_code','name','close','rank']} for pick in row['picks']]) for row in strategies])
    validate_snapshot(value)
    folder=root/'jobs/daily/selections'/date
    if folder.resolve()!=folder:raise ValueError('精选快照目录无效')
    folder.mkdir(parents=True,exist_ok=True,mode=0o770)
    path=folder/(generation+'.json')
    if path.exists():
        existing=read_snapshot(root,path)
        if existing!=value:raise ValueError('同版本精选快照不允许改写')
        return existing
    envelope={'snapshot':value,'sha256':digest(value)}
    fd,temporary=tempfile.mkstemp(prefix='.selection-',dir=folder)
    try:
        os.fchmod(fd,0o660)
        with os.fdopen(fd,'w') as output:
            json.dump(envelope,output,ensure_ascii=False,allow_nan=False);output.flush();os.fsync(output.fileno())
        try:os.link(temporary,path)
        except FileExistsError:
            if read_snapshot(root,path)!=value:raise ValueError('同版本精选快照不允许改写')
        parent=os.open(folder,os.O_RDONLY)
        try:os.fsync(parent)
        finally:os.close(parent)
    finally:Path(temporary).unlink(missing_ok=True)
    return value


def eligible_before_open(snapshot,date):
    start=datetime.strptime(date,'%Y%m%d').replace(tzinfo=ZONE)
    if snapshot['timing_basis']=='closing_receipt':
        return snapshot['published_at']<start.replace(hour=9,minute=30).timestamp()
    # Old generations lack a publication receipt. Never use a version first
    # generated on the evaluation day as if it had been yesterday's selection.
    return generation_time(snapshot['generation'])<start.timestamp()


def read_legacy_generation(root,generation,date,receipt=None):
    root=Path(root).resolve();folder=root/'releases'/generation;groups=[];revision=None;universe=None
    ids=STRATEGIES if (folder/'left_rebound/manifest.json').exists() else HISTORICAL_STRATEGIES
    for strategy in ids:
        location=folder/strategy
        header=json.loads(checked_file(folder,location/'manifest.json',65536).read_text())
        raw=checked_file(folder,location/'report.json',MAX_REPORT).read_bytes()
        if (header.get('generation')!=generation or header.get('as_of')!=date or header.get('strategy')!=strategy
                or header.get('report_bytes')!=len(raw) or header.get('report_sha256')!=hashlib.sha256(raw).hexdigest()):
            raise ValueError('历史精选报告校验失败')
        report=json.loads(raw);stocks=report.get('stocks',[]);codes={row['ts_code'] for row in stocks}
        if (report.get('as_of')!=date or report.get('strategy_id')!=strategy
                or report.get('data_revision')!=header.get('data_revision')
                or revision is not None and revision!=header['data_revision']
                or len(codes)!=len(stocks) or universe is not None and universe!=codes):
            raise ValueError('历史精选四策略未对齐')
        if receipt is not None:
            update=report.get('last_update') or {}
            if (header['data_revision']!=receipt.get('data_revision')
                    or update.get('close_attestation')!=receipt.get('close_attestation')
                    or update.get('forced_latest_date')!=date):raise ValueError('精选报告与发布时间凭证不一致')
        revision=header['data_revision'];universe=codes
        picks=[row for row in stocks if row.get('state')=='入选']
        if len(picks)!=report.get('shortlist_count') or any(row.get('trade_date')!=date for row in picks):
            raise ValueError('历史精选日期或数量无效')
        groups.append(dict(id=strategy,name=report['strategy_name'],picks=sorted(picks,key=lambda row:row['rank'])))
    return save_snapshot(root,date,generation,revision,groups,receipt['published_at'] if receipt else None)


def find_previous_snapshot(root,signal_date,evaluation_date):
    root=Path(root).resolve()
    if not valid_date(signal_date) or not valid_date(evaluation_date) or signal_date>=evaluation_date:
        raise ValueError('精选与评价日期无效')
    folder=Path(root)/'jobs/daily/selections'/signal_date;qualified=[];known=set()
    if folder.exists():
        for path in folder.glob('*.json'):
            value=read_snapshot(root,path)
            if value['date']!=signal_date or path.stem!=value['generation']:raise ValueError('精选路径与内容不一致')
            known.add(value['generation'])
            if eligible_before_open(value,evaluation_date):qualified.append(value)
    if qualified:
        return max(qualified,key=lambda value:value.get('published_at') or generation_time(value['generation']))
    receipt_root=Path(root)/'jobs/closing-receipts';receipt_path=receipt_root/(signal_date+'.json')
    if receipt_path.exists():
        receipt=json.loads(checked_file(receipt_root,receipt_path,65536).read_text())
        generation=receipt.get('generation');generation_time(generation)
        published=receipt.get('published_at')
        if receipt.get('date')!=signal_date or type(published) not in [int,float] or not 0<published<1e12:
            raise ValueError('历史精选发布时间凭证无效')
        cutoff=datetime.strptime(evaluation_date,'%Y%m%d').replace(tzinfo=ZONE,hour=9,minute=30).timestamp()
        if generation not in known and published<cutoff:
            return read_legacy_generation(root,generation,signal_date,receipt)
        known.add(generation)
    releases=Path(root)/'releases'
    if releases.is_dir():
        for directory in sorted(releases.iterdir(),key=lambda path:path.name,reverse=True):
            if (not GENERATION.fullmatch(directory.name) or directory.name[:8]>=evaluation_date
                    or directory.name in known):continue
            header_path=directory/'leaders/manifest.json'
            header=json.loads(checked_file(directory,header_path,65536).read_text())
            if header.get('as_of')==signal_date:
                return read_legacy_generation(root,directory.name,signal_date)
    return None
