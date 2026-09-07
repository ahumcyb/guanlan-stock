"""Content-bound evidence that a closing day was fetched after the review cutoff.

Top-level imports stay lightweight so queue/API validation does not import pandas.
"""
import hashlib
import json
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

ZONE = ZoneInfo('Asia/Shanghai')
TABLES = ('daily', 'adj_factor', 'stk_limit')


def valid_date(value):
    if not isinstance(value,str) or not re.fullmatch(r'[0-9]{8}',value):
        return False
    try:
        datetime.strptime(value,'%Y%m%d')
        return True
    except ValueError:
        return False


def closing_cutoff(date):
    if not valid_date(date):
        raise ValueError('收盘总结日期无效')
    return datetime.strptime(date,'%Y%m%d').replace(hour=16,minute=10,tzinfo=ZONE)


def day_digest(frame, kind, date):
    from .data import FIELDS, validate
    clean=validate(frame,kind)
    if clean.empty or not clean.trade_date.eq(date).all():
        raise ValueError('收盘证明必须绑定完整目标日期切片')
    clean=clean.sort_values('ts_code').reset_index(drop=True)
    for name in FIELDS[kind][2:]:
        clean[name]=clean[name].astype(float)
    encoded=clean[FIELDS[kind]].to_json(orient='records',double_precision=10).encode()
    return {'rows':len(clean),'sha256':hashlib.sha256(encoded).hexdigest()}


def make_attestation(date, frames, now=None):
    now=now or datetime.now(ZONE)
    if now.tzinfo is None or now<closing_cutoff(date):
        raise ValueError('收盘总结须在交易日 16:10 后重新核验行情')
    return {'schema_version':1,'date':date,'fetched_at':now.isoformat(),
            'tables':{kind:day_digest(frames[kind],kind,date) for kind in TABLES}}


def verify_attestation(value, date, frames, now=None):
    now=now or datetime.now(ZONE)
    if (not isinstance(value,dict) or set(value)!={'schema_version','date','fetched_at','tables'}
            or value['schema_version']!=1 or value['date']!=date or not isinstance(value['fetched_at'],str)):
        raise ValueError('缺少有效收盘数据证明')
    try:
        fetched=datetime.fromisoformat(value['fetched_at'])
    except ValueError:
        raise ValueError('收盘核验时间无效') from None
    if fetched.tzinfo is None or fetched<closing_cutoff(date) or fetched>now+timedelta(minutes=5):
        raise ValueError('收盘核验时间不在允许范围')
    if not isinstance(value['tables'],dict) or set(value['tables'])!=set(TABLES):
        raise ValueError('收盘三表证明不完整')
    for kind in TABLES:
        expected=value['tables'][kind]
        if not isinstance(expected,dict) or type(expected.get('rows')) is not int or expected!=day_digest(frames[kind],kind,date):
            raise ValueError('收盘证明与实际数据不一致')


def verify_package_close(root, date, proof, now=None):
    import pandas as pd
    from .data import FIELDS, validate
    manifest=json.loads((root/'manifest.json').read_text())
    if manifest.get('as_of')!=date:
        raise ValueError('发布行情不是要求的收盘日期')
    frames={kind:validate(pd.read_parquet(root/'raw'/(kind+'.parquet'),columns=FIELDS[kind],
                        filters=[('trade_date','==',date)]),kind) for kind in TABLES}
    codes=set(frames['daily'].ts_code)
    if len(codes)<4000:
        raise ValueError('收盘日线覆盖不足')
    for kind,fraction in [('adj_factor',1),('stk_limit',.99)]:
        if len(codes & set(frames[kind].ts_code))<len(codes)*fraction:
            raise ValueError('收盘配套数据覆盖不足')
    verify_attestation(proof,date,frames,now)
    return frames


def read_closing_partition(overlay, date):
    import pandas as pd
    from .data import FIELDS
    record=json.loads((overlay/'last_update.json').read_text())
    generation=record.get('closing_generation','')
    if not re.fullmatch(re.escape(date)+r'-[a-f0-9]{12}',generation):
        raise ValueError('收盘重抓分区标识无效')
    folder=overlay/'closing'/generation/date
    if folder.is_symlink() or folder.resolve()!=folder or not folder.is_dir():
        raise ValueError('收盘重抓分区路径无效')
    frames={kind:pd.read_parquet(folder/(kind+'.parquet'),columns=FIELDS[kind]) for kind in TABLES}
    verify_attestation(record.get('close_attestation'),date,frames)
    return frames
