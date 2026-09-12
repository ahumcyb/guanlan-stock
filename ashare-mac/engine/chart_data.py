"""Bounded extended chart sidecars; independent of the strategy/AI process."""
import gzip
import json
import math
import re
from pathlib import Path

from .close_proof import valid_date
from .snapshot_protocol import REVISION

MAX_EXTENDED=512*1024
MAX_COMPRESSED=128*1024
LEGACY_FIELDS=['date','open','high','low','close','ma10','ma20','ma60','volume']
RAW_FIELDS=['raw_open','raw_high','raw_low','raw_close','raw_pre_close','amount']
CODE=re.compile(r'^\d{6}\.(SH|SZ|BJ)$')


def number(value,positive=False):
    return type(value) in [int,float] and math.isfinite(value) and (value>0 if positive else value>=0)


def validate_extended(value,code,as_of,revision,legacy=None):
    if (not isinstance(value,dict) or set(value)!={'schema_version','ts_code','as_of','data_revision','price_basis','volume_unit','bars'}
            or type(value['schema_version']) is not int or value['schema_version']!=1
            or not isinstance(code,str) or not CODE.fullmatch(code) or value['ts_code']!=code
            or not valid_date(as_of) or value['as_of']!=as_of or value['data_revision']!=revision
            or revision is not None and (not isinstance(revision,str) or not REVISION.fullmatch(revision))
            or value['price_basis']!='continuous_latest_close' or value['volume_unit']!='lot'):
        raise ValueError('扩展K线身份或单位无效')
    bars=value['bars']
    if not isinstance(bars,list) or not 1<=len(bars)<=500:raise ValueError('扩展K线数量无效')
    dates=[]
    for bar in bars:
        if not isinstance(bar,dict) or set(bar)!=set(LEGACY_FIELDS+RAW_FIELDS):raise ValueError('扩展K线字段无效')
        day=bar['date'];dates.append(day)
        if not valid_date(day) or day>as_of:raise ValueError('扩展K线日期无效')
        for prefix in ['', 'raw_']:
            prices=[bar[prefix+key] for key in ['open','high','low','close']]
            if not all(number(p,True) for p in prices):raise ValueError('扩展K线价格无效')
            opened,high,low,close=prices
            if high+1e-6<max(opened,close,low) or low-1e-6>min(opened,close):raise ValueError('扩展K线OHLC无效')
        if (not number(bar['raw_pre_close'],True) or not number(bar['volume']) or not number(bar['amount'])
                or any(bar[key] is not None and not number(bar[key],True) for key in ['ma10','ma20','ma60'])):
            raise ValueError('扩展K线量额或均线无效')
        scale=bar['close']/bar['raw_close']
        if any(abs(bar[key]-bar['raw_'+key]*scale)>max(1e-5,abs(bar[key])*1e-6) for key in ['open','high','low']):
            raise ValueError('扩展K线价格口径不一致')
    if dates!=sorted(set(dates)):raise ValueError('扩展K线重复或乱序')
    if abs(bars[-1]['close']-bars[-1]['raw_close'])>1e-6:
        raise ValueError('连续价格没有锚定最新收盘')
    for previous,current in zip(bars,bars[1:]):
        ratio=current['raw_close']/current['raw_pre_close'];expected=previous['close']*ratio
        if abs(current['close']-expected)>2e-6*(1+abs(ratio))+abs(expected)*1e-8:
            raise ValueError('连续价格与原始涨跌链不一致')
    if legacy is not None:
        expected=[{k:bar[k] for k in LEGACY_FIELDS} for bar in bars[-120:]]
        if legacy!=expected:raise ValueError('新旧K线内容不一致')
    return value


def make_extended(group,code,as_of,revision):
    # Same normalization and decimal precision as the original 120-bar export.
    frame=group.tail(500).copy();scale=float(group.close.iloc[-1]/group.price.iloc[-1])
    selected=frame[['trade_date','adj_open','adj_high','adj_low','price','ma10','ma20','ma60','vol',
                    'open','high','low','close','pre_close','amount']].copy()
    for name in ['adj_open','adj_high','adj_low','price','ma10','ma20','ma60']:selected[name]*=scale
    selected.columns=LEGACY_FIELDS+RAW_FIELDS
    bars=json.loads(selected.to_json(orient='records',double_precision=6))
    value=dict(schema_version=1,ts_code=code,as_of=as_of,data_revision=revision,
               price_basis='continuous_latest_close',volume_unit='lot',bars=bars)
    return validate_extended(value,code,as_of,revision)


def write_extended(path,value):
    data=json.dumps(value,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode()
    if len(data)>MAX_EXTENDED:raise ValueError('扩展K线超过大小限制')
    packed=gzip.compress(data,compresslevel=6,mtime=0)
    if len(packed)>MAX_COMPRESSED:raise ValueError('扩展K线压缩文件过大')
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(packed)


def read_extended(path,code,as_of,revision,legacy=None,consume=None):
    path=Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size>MAX_COMPRESSED:raise ValueError('扩展K线文件无效')
    with gzip.open(path,'rb') as source:data=source.read(MAX_EXTENDED+1)
    if len(data)>MAX_EXTENDED:raise ValueError('扩展K线解压后超过大小限制')
    if consume:consume(len(data))
    def unique(pairs):
        value={}
        for key,item in pairs:
            if key in value:raise ValueError('扩展K线有重复字段')
            value[key]=item
        return value
    value=json.loads(data,object_pairs_hook=unique)
    if data!=json.dumps(value,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode():
        raise ValueError('扩展K线编码不是规范格式')
    return validate_extended(value,code,as_of,revision,legacy)


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--folder',type=Path,required=True)
    parser.add_argument('--code',required=True);parser.add_argument('--as-of',required=True);parser.add_argument('--revision')
    args=parser.parse_args()
    try:
        if not CODE.fullmatch(args.code):raise ValueError('Invalid code')
        value=read_extended(args.folder/'charts-extended'/(args.code+'.json.gz'),args.code,args.as_of,args.revision)
        print(json.dumps(value,ensure_ascii=False,allow_nan=False,separators=(',',':')))
    except (OSError,ValueError,KeyError,TypeError):raise SystemExit(1)
