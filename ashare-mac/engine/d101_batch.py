"""Date-checked D101 prescreen; every potential selection uses a D6 quote."""
import json
import math
import time
from dataclasses import dataclass

from .datta import CODE, DattaError, number, date_value, check_prices, unique_object, validate_base_url
from .intraday import local_now, normalize_quote, trading_minutes

FIELDS=['code','name','decimal_num','volume_unit_flag','trade_date','price','open_price',
        'high','low','pre_close','volume','amount']
MAX_BYTES=8*1024*1024


class BatchFallback(ValueError):
    """A safe reason code, never a provider payload or exception message."""


@dataclass
class BatchCapture:
    rows:dict
    received_at:float
    diagnostics:dict


def decode_batch_row(raw,expected_date):
    try:
        code=raw['code']
        if not isinstance(code,str) or len(code)!=8:
            raise BatchFallback('invalid_code')
        code=code[2:]+'.'+code[:2]
        if not CODE.fullmatch(code):raise BatchFallback('invalid_code')
        day=date_value(raw['trade_date']).strftime('%Y%m%d')
        if day!=expected_date:raise BatchFallback('wrong_trade_date')
        decimals=raw['decimal_num'];unit=raw['volume_unit_flag']
        if type(decimals) is not int or not 0<=decimals<=6 or type(unit) is not int or unit not in [0,1]:
            raise BatchFallback('invalid_units')
        names=dict(open='open_price',high='high',low='low',close='price',pre_close='pre_close')
        row={key:number(raw[value],True)/10**decimals for key,value in names.items()}
        row.update(vol=number(raw['volume'],True)*(100 if unit==1 else 1),amount=number(raw['amount'],True))
        check_prices(row)
        row.update(ts_code=code,name=str(raw.get('name') or '').strip()[:30],trade_date=day)
        return row
    except BatchFallback:raise
    except (KeyError,TypeError,ValueError,AttributeError,OverflowError):
        raise BatchFallback('invalid_row') from None


def capture_batch(base_url,codes,expected_date,connector=None,clock=time.time,budget=8.):
    base_url=validate_base_url(base_url);date_value(expected_date)
    if (not isinstance(codes,list) or not codes or len(codes)>6500 or len(set(codes))!=len(codes)
            or any(not isinstance(code,str) or not CODE.fullmatch(code) for code in codes)):
        raise BatchFallback('invalid_universe')
    if connector is None:
        try:from websockets.sync.client import connect
        except ImportError:raise BatchFallback('batch_dependency_unavailable') from None
        connector=connect
    wanted={code[-2:]+code[:6] for code in codes};cache={};conflicts=set();frames=0;bytes_read=0
    started=time.monotonic();last_new=started;received=clock()
    try:
        with connector('ws'+base_url[4:]+'/d101',proxy=None,compression=None,open_timeout=5,
                       close_timeout=1,max_size=MAX_BYTES,max_queue=4) as ws:
            ws.send(json.dumps(dict(type='snapshot',seq=1,enable=1,codes=sorted(wanted),fields=FIELDS)))
            while frames<128 and time.monotonic()-started<budget:
                remaining=budget-(time.monotonic()-started)
                if len(cache)>=len(codes)*.95:
                    remaining=min(remaining,.35-(time.monotonic()-last_new))
                if remaining<=0:break
                try:raw=ws.recv(timeout=remaining)
                except TimeoutError:break
                received=clock();frames+=1;bytes_read+=len(raw)
                if len(raw)>MAX_BYTES or bytes_read>32*1024*1024:raise BatchFallback('batch_too_large')
                payload=json.loads(raw,object_pairs_hook=unique_object)
                if not isinstance(payload,dict) or not isinstance(payload.get('list'),list):
                    raise BatchFallback('invalid_envelope')
                sent=number(payload.get('ts'))/1000
                if not -15<=received-sent<=15:raise BatchFallback('stale_transport')
                frame_values={}
                for item in payload['list']:
                    if not isinstance(item,dict):raise BatchFallback('invalid_envelope')
                    if item.get('type')=='error':raise BatchFallback('provider_error')
                    if item.get('type') not in ['snapshot','zxg']:continue
                    if not isinstance(item.get('data'),list):raise BatchFallback('invalid_envelope')
                    for row in item['data']:
                        if not isinstance(row,dict):raise BatchFallback('invalid_row')
                        code=row.get('code')
                        if code not in wanted:continue
                        selected={key:value for key,value in row.items() if key in FIELDS}
                        previous=frame_values.get(code,{})
                        if any(key in previous and previous[key]!=value for key,value in selected.items()):
                            conflicts.add(code);cache.pop(code,None);continue
                        frame_values.setdefault(code,{}).update(selected)
                for code,row in frame_values.items():
                    if code in conflicts:continue
                    previous=cache.get(code,{})
                    if any(key in row and key in previous and row[key]!=previous[key]
                           for key in ['trade_date','decimal_num','volume_unit_flag']):
                        previous={}
                    if code not in cache:last_new=time.monotonic()
                    cache[code]=dict(previous,**row)
                valid={}
                for code,row in cache.items():
                    try:value=decode_batch_row(row,expected_date)
                    except BatchFallback:continue
                    valid[value['ts_code']]=value
                if len(valid)==len(codes):break
    except BatchFallback:raise
    except Exception:
        raise BatchFallback('batch_connection_or_schema') from None
    rows={}
    for raw in cache.values():
        try:value=decode_batch_row(raw,expected_date)
        except BatchFallback:continue
        rows[value['ts_code']]=value
    return BatchCapture(rows,received,dict(frames=frames,bytes=bytes_read,conflicts=len(conflicts),
                                          elapsed_seconds=round(time.monotonic()-started,3)))


def potential_codes(rows,features,now,include_bottom):
    """A deliberately wider envelope than any final rule; never truncate by rank."""
    result=set();elapsed=trading_minutes(now)
    for code,row in rows.items():
        feature=features.get(code,{})
        try:
            average=number(feature.get('mean_volume5'),True)
            reference=number(feature.get('last_close'),True)
            if abs(row['pre_close']-reference)>1e-6:
                result.add(code)
                continue
            change=(row['close']/row['pre_close']-1)*100
            multiple=row['vol']/average
            if 2.5<=change<=5.5 and multiple>=.75*elapsed/240:
                result.add(code)
            if include_bottom:
                low=number(feature.get('low60'),True)
                if -.5<=change and .99<=row['close']/low<=1.12 and multiple>=2.3:
                    result.add(code)
        except (ValueError,KeyError,TypeError,ZeroDivisionError):
            # Uncertain inputs must be verified, rather than excluded cheaply.
            result.add(code)
    return result


def sample_codes(codes,size=20):
    codes=sorted(codes)
    if len(codes)<=size:return set(codes)
    return {codes[round(i*(len(codes)-1)/(size-1))] for i in range(size)}


def compatible(first,second):
    for key in ['pre_close','open']:
        # These prices are fixed during the session. A cent is a material
        # percentage for low-price stocks, so permit only float representation.
        if abs(first[key]-second[key])>1e-6:return False
    if abs(first['close']/second['close']-1)>.003:return False
    for key in ['vol','amount']:
        if abs(first[key]/second[key]-1)>.05:return False
    return True


def verify_batch(capture,codes,features,client,now,include_bottom,clock=local_now):
    if len(capture.rows)<len(codes)*.90:raise BatchFallback('insufficient_batch_coverage')
    if not -15<=now.timestamp()-capture.received_at<=30:raise BatchFallback('old_batch_capture')
    potential=potential_codes(capture.rows,features,now,include_bottom)
    missing=set(codes)-set(capture.rows)
    if len(potential|missing)>1000:raise BatchFallback('verification_pool_too_large')
    samples=sample_codes(capture.rows)
    requested=potential|missing|samples
    def accepted(raw,at):
        valid={};normalized={}
        for row in raw:
            code=row.get('ts_code')
            if code not in requested:continue
            try:quote=normalize_quote(row,at)
            except (TypeError,ValueError):continue
            valid[code]=row;normalized[code]=quote
        return valid,normalized
    raw=client.quotes(sorted(requested));valid,normalized=accepted(raw,clock())
    missing_d6=requested-set(valid);retry_count=0
    if 0<len(missing_d6)<=20 and len(valid)>=len(requested)*.9:
        retry_count=len(missing_d6)
        retried=client.quotes(sorted(missing_d6))
        valid,normalized=accepted(list(valid.values())+retried,clock())
    if potential-set(valid):raise BatchFallback('candidate_not_verified')
    checked=samples & set(valid)
    if len(checked)<max(1,math.ceil(len(samples)*.9)):
        raise BatchFallback('health_sample_not_verified')
    if any(not compatible(capture.rows[code],normalized[code]) for code in checked):
        raise BatchFallback('health_sample_mismatch')
    diagnostics=dict(provider='datta_d6',mode='d101_batch_verified',requested=len(codes),
        batch_count=len(capture.rows),batch_received_at=capture.received_at,
        coverage_count=len(set(capture.rows)|set(valid)),verified_count=len(valid),
        potential_count=len(potential),sample_count=len(checked),d6_retry_count=retry_count,
        unavailable=len(codes)-len(set(capture.rows)|set(valid)),batch=capture.diagnostics)
    return [valid[code] for code in sorted(valid)],diagnostics
