"""Bounded ProMax acquisition and a small, independent intraday feature cache."""
import json
import math
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, build_opener
from urllib.error import HTTPError, URLError

import pandas as pd

from .data import atomic_json, combine, source_paths, full_market_dates, minimum_market_rows, validate
from .intraday import CODE, local_now, normalize_quote, screen,bottom_volume_screen,BOTTOM_RULE_VERSION
from .provider import BASE_URL, NoRedirect, ProMax, parse_response
from .sina_quotes import fetch_quotes as sina_quotes

FIELDS = 'ts_code,name,pre_close,open,high,low,close,vol,amount,trade_time'
QUOTE_FIELDS = FIELDS + ',updated_at'


def incomplete_days(counts, days, previous):
    complete = set(full_market_dates(counts))
    if not complete:
        raise ValueError('找不到完整的历史基准日')
    latest = max(complete)
    return [d for d in days if latest < d <= previous]


def check_day(frame, date, counts):
    checked = validate(frame, 'daily')
    if set(checked.trade_date) != {date} or len(checked) < minimum_market_rows(counts, date):
        raise ValueError('前日行情低于近期覆盖基准的97%')
    return checked


def checked_shares(frame, date, expected_codes):
    if not {'ts_code', 'trade_date', 'float_share'}.issubset(frame) or frame.ts_code.duplicated().any() or set(frame.trade_date) != {date}:
        raise ValueError('流通股本数据格式无效')
    numeric = pd.to_numeric(frame.float_share, errors='coerce')
    usable = frame[numeric.gt(0) & numeric.lt(float('inf'))].copy()
    if not expected_codes or len(set(usable.ts_code) & expected_codes) < len(expected_codes) * .97:
        raise ValueError('流通股本对前日股票池覆盖不足97%')
    return dict(zip(usable.ts_code, numeric.loc[usable.index] * 10000))


def canonical_snapshots(frame):
    columns = FIELDS.split(',')
    if not set(columns).issubset(frame.columns):
        raise ValueError('实时快照缺少必要字段')
    # ProMax may repeat the same quote with transport timestamps one second apart.
    # Merge only equal values used by the rules; keep the oldest timestamp so this
    # normalization can never make an old quote appear newer. Conflicts are omitted.
    distinct = frame.drop_duplicates(columns)
    conflicts = set(distinct.loc[distinct.ts_code.duplicated(False), 'ts_code'])
    clean = frame[~frame.ts_code.isin(conflicts)]
    if 'updated_at' in clean:
        clean = clean.sort_values('updated_at', na_position='first')
    return clean.drop_duplicates('ts_code'), len(conflicts)


class IntradayProvider(ProMax):
    def get(self, api, **params):
        if api not in {'rt_k', 'rt_idx_k', 'rt_min_daily', 'daily_basic', 'daily', 'adj_factor', 'trade_cal', 'stock_basic'}:
            raise ValueError('不支持的盘中数据接口')
        request = Request(BASE_URL + '/' + api + '?' + urlencode(params),
                          headers={'X-API-Key': self._secret, 'Accept': 'application/json'})
        for attempt in range(2):
            try:
                timeout=5 if api=='rt_min_daily' else (6 if api in {'rt_k','rt_idx_k'} else 25)
                with build_opener(NoRedirect()).open(request, timeout=timeout) as response:
                    raw = response.read(4 * 1024 * 1024 + 1)
                if len(raw) > 4 * 1024 * 1024 or self._secret.encode() in raw:
                    raise ValueError()
                payload = json.loads(raw)
                if isinstance(payload, dict) and payload.get('code') == -1000 and attempt == 0:
                    time.sleep(.5)
                    continue
                frame = parse_response(payload)
                if len(frame) > 6500 or self._secret in frame.to_json(force_ascii=False):
                    raise ValueError()
                return frame
            except HTTPError as error:
                if attempt or error.code not in (429, 500, 502, 503, 504):
                    raise ValueError(f'ProMax {api} HTTP {error.code}') from None
            except (TimeoutError, URLError, OSError):
                if attempt:
                    raise ValueError(f'ProMax {api} 连接超时') from None
            except Exception:
                raise ValueError('ProMax ' + api + ' 响应无效') from None
            time.sleep(.5)

    @staticmethod
    def valid_rows(rows,codes,index=False):
        wanted=set(codes);valid={};conflicts=set();now=local_now()
        for original in rows:
            if not isinstance(original,dict) or original.get('ts_code') not in wanted:continue
            row={key:original[key] for key in QUOTE_FIELDS.split(',') if key in original}
            try:normalize_quote(row,now,index=index)
            except (ValueError,TypeError):continue
            code=row['ts_code']
            if code in valid and valid[code]!=row:conflicts.add(code)
            else:valid[code]=row
        return {code:row for code,row in valid.items() if code not in conflicts}

    def quote_batch(self,codes,fallback,api='rt_k',index=False):
        primary={};diagnostic=dict(primary_requests=0,fallback_requests=0,primary_rejected=0,
                                   primary_errors=0,fallback_errors=0,conflicts=0)
        if not fallback.is_set():
            diagnostic['primary_requests']=1
            try:
                # Explicit codes work with both ProMax backends; retain its source update time.
                frame=self.get(api,ts_code=','.join(codes),fields=QUOTE_FIELDS)
                if not frame.empty:
                    if 'ts_code' not in frame or not set(frame.ts_code).issubset(set(codes)):
                        raise ValueError('主源股票集合不一致')
                    frame=frame.copy()
                    if 'trade_time' not in frame:frame['trade_time']=''
                    frame,conflicts=canonical_snapshots(frame);diagnostic['conflicts']=conflicts
                    primary=self.valid_rows(json.loads(frame.to_json(orient='records')),codes,index)
            except Exception:
                diagnostic['primary_errors']=1
                primary={}
        missing=[code for code in codes if code not in primary]
        diagnostic['primary_rejected']=len(missing) if diagnostic['primary_requests'] else 0
        rows={code:dict(row,quote_source='promax') for code,row in primary.items()}
        if missing:
            # Once the primary is broadly unusable, don't repeat slow failed calls for every batch.
            if len(missing)>len(codes)*.1:fallback.set()
            diagnostic['fallback_requests']=1
            try:
                replacement=self.valid_rows(sina_quotes(missing),missing,index)
                rows.update({code:dict(row,quote_source='sina') for code,row in replacement.items()})
            except Exception:
                diagnostic['fallback_errors']=1
        diagnostic.update(promax_quotes=sum(row['quote_source']=='promax' for row in rows.values()),
                          sina_quotes=sum(row['quote_source']=='sina' for row in rows.values()),
                          unavailable=len(codes)-len(rows))
        return list(rows.values()),diagnostic

    def quotes(self,codes):
        if (not isinstance(codes,list) or len(codes)>6500 or len(set(codes))!=len(codes)
                or any(not isinstance(code,str) or not CODE.fullmatch(code) for code in codes)):
            raise ValueError('股票集合无效')
        start=time.monotonic();batches=[codes[i:i+200] for i in range(0,len(codes),200)]
        fallback=threading.Event();rows=[];diagnostics=[]
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures=[pool.submit(self.quote_batch,batch,fallback) for batch in batches]
            for future in futures:
                values,diagnostic=future.result();rows.extend(values);diagnostics.append(diagnostic)
        self.quote_diagnostics={name:sum(item[name] for item in diagnostics) for name in
            ['primary_requests','fallback_requests','primary_rejected','primary_errors','fallback_errors',
             'promax_quotes','sina_quotes','unavailable','conflicts']}
        self.quote_diagnostics.update(batches=len(batches),elapsed_seconds=round(time.monotonic()-start,3))
        self.conflicting_quotes=self.quote_diagnostics['conflicts']
        return rows

    def index_quote(self,code='000300.SH'):
        if code!='000300.SH':raise ValueError('指数代码无效')
        rows,self.index_diagnostics=self.quote_batch([code],threading.Event(),api='rt_idx_k',index=True)
        return rows[0] if rows else None


def read_calendar(root, cache, provider=None):
    now = local_now(); start = (now - timedelta(days=30)).strftime('%Y%m%d'); end = (now + timedelta(days=45)).strftime('%Y%m%d')
    path = cache / 'calendar.parquet'
    source = path if path.exists() else root / 'raw/trade_cal.parquet'
    frame = pd.read_parquet(source)
    frame = frame[frame.exchange == 'SSE'].drop_duplicates('cal_date')
    if frame.cal_date.min() > start or frame.cal_date.max() < end:
        if provider is None:
            raise ValueError('交易日历需要更新')
        frame = provider.get('trade_cal', exchange='SSE', start_date=start, end_date=end)
        from .update import validate_calendar
        validate_calendar(frame, start, end)
        pending = path.with_suffix('.pending.parquet');frame.to_parquet(pending, index=False);pending.replace(path)
    return sorted(frame.loc[frame.is_open == 1, 'cal_date'].astype(str))


def features_for(root, cache, provider, now=None):
    root = root.resolve()  # Pin one immutable generation across all table reads.
    now = now or local_now(); date = now.strftime('%Y%m%d'); cache.mkdir(parents=True, exist_ok=True)
    days = read_calendar(root, cache, provider)
    prior = [d for d in days if d < date]
    if not prior:
        raise ValueError('缺少前一交易日历')
    previous = prior[-1]
    version = root.resolve().name
    target = cache / ('features-' + date + '.json')
    if target.exists():
        value = json.loads(target.read_text())
        if value.get('schema_version') == 3 and value.get('source_version') == version and value.get('previous') == previous and not value.get('warnings'):
            return value
    start = (now - timedelta(days=180)).strftime('%Y%m%d')
    tables = {}
    for kind in ['daily', 'adj_factor']:
        paths = source_paths(root, cache, kind)
        frames = [pd.read_parquet(p, filters=[('trade_date', '>=', start), ('trade_date', '<=', previous)]) for p in paths]
        tables[kind] = combine(frames, kind)
    counts = tables['daily'].groupby('trade_date').size().sort_index()
    missing = incomplete_days(counts, days, previous)
    if len(missing) > 15:
        raise ValueError('历史数据落后超过15个交易日，请先更新数据')
    for day in missing:
        new = {}
        for kind in ['daily', 'adj_factor']:
            new[kind] = provider.get(kind, trade_date=day, limit=6500)
            if 'trade_date' not in new[kind] or set(new[kind].trade_date) != {day}:
                raise ValueError('前日行情覆盖不足')
        new['daily'] = check_day(new['daily'], day, counts)
        if not set(new['daily'].ts_code).issubset(set(new['adj_factor'].ts_code)):
            raise ValueError('前日复权数据覆盖不足')
        # This is an intraday-only cache; it never writes the completed-bar repository.
        folder = cache / 'updates' / day;folder.mkdir(parents=True, exist_ok=True)
        for kind in new:
            # Replace a known incomplete partition only inside this private cache.
            merged = combine([tables[kind][tables[kind].trade_date != day], new[kind]], kind)
            pending = folder / (kind + '.pending.parquet');new[kind].to_parquet(pending, index=False);pending.replace(folder / (kind + '.parquet'))
            tables[kind] = merged
        counts = tables['daily'].groupby('trade_date').size().sort_index()
    prior_daily = check_day(tables['daily'][tables['daily'].trade_date == previous], previous, counts)
    expected_codes = set(prior_daily.ts_code)
    if not expected_codes.issubset(set(tables['adj_factor'].loc[tables['adj_factor'].trade_date == previous, 'ts_code'])):
        raise ValueError('前一交易日复权因子覆盖不足')
    basic = pd.read_parquet(root / 'raw/stock_basic.parquet').set_index('ts_code')
    warning = []
    share_map = {}
    try:
        shares = provider.get('daily_basic', trade_date=previous, fields='ts_code,trade_date,float_share', limit=6500)
        share_map = checked_shares(shares, previous, expected_codes)
    except Exception:
        warning.append('前日流通股本不可用，七步法暂不生成候选')
    data = tables['daily'].merge(tables['adj_factor'], on=['ts_code', 'trade_date'], how='left', validate='one_to_one')
    features = {}
    for code, group in data.groupby('ts_code', sort=False):
        if not CODE.fullmatch(code) or code not in basic.index:
            continue
        name = str(basic.loc[code, 'name'])
        if 'ST' in name.upper() or '退' in name:
            continue
        group = group.sort_values('trade_date').tail(60)
        if (len(group) < 60 or group.iloc[-1].trade_date != previous or group.adj_factor.isna().any()
                or group.trade_date.tail(5).tolist() != prior[-5:]):
            continue
        prices = group.close * group.adj_factor / group.iloc[-1].adj_factor
        highs = group.high * group.adj_factor / group.iloc[-1].adj_factor
        lows = group.low * group.adj_factor / group.iloc[-1].adj_factor
        mean_volume = float(group.vol.tail(5).mean()) * 100  # daily lots -> shares
        if mean_volume <= 0:
            continue
        floating = float(share_map.get(code, 0))
        features[code] = dict(name=name[:30], date=previous, observations=len(group), adjusted=True, last_close=float(group.iloc[-1].close),
            sum4=float(prices.tail(4).sum()), sum9=float(prices.tail(9).sum()), sum19=float(prices.tail(19).sum()),
            ma5=float(prices.tail(5).mean()), platform_high=float(highs.tail(10).max()),
            platform_range=float(prices.tail(10).max() / prices.tail(10).min()), mean_volume5=mean_volume,
            low60=float(lows.min()),float_shares=floating if math.isfinite(floating) and floating > 0 else 0)
    if len(features) < 3500:
        raise ValueError('历史特征可用股票不足3500只')
    value = dict(schema_version=3, date=date, previous=previous, source_version=version, open_dates=days, features=features, warnings=warning)
    atomic_json(target, value)
    # Features are tiny, still keep bounded retention.
    for old in sorted(cache.glob('features-*.json'))[:-10]:
        old.unlink()
    return value


def _run(root, cache, kind='screen', previous_candidates=None, provider=None, progress=None,slot_id=None):
    root = root.resolve()
    progress=progress or (lambda stage:None)
    progress('credentials')
    provider = provider or IntradayProvider(); now = local_now()
    progress('history')
    value = features_for(root, cache, provider, now)
    report = dict(schema_version=1, date=now.strftime('%Y%m%d'), generated_at=now.timestamp(),
                  previous_date=value['previous'], source_version=value['source_version'], kind=kind,
                  strategies={'overnight': [], 'golden': []}, reviews=[], warnings=list(value['warnings']),
                  universe_count=len(value['features']), quote_count=0, fresh_count=0, status='ready')
    if report['date'] not in value['open_dates']:
        report.update(status='closed', message='今日休市，未请求实时行情')
        return report
    if kind == 'prepare':
        report['message'] = '盘中历史特征与参考股本已准备'
        return report
    if kind == 'screen' and not '1430' <= now.strftime('%H%M') < '1453':
        report.update(status='blocked',run_state='waiting',message='当前不在14:30–14:50策略时段，已准备历史特征；等待交易日定时执行')
        return report
    codes = sorted(value['features']) if kind == 'screen' else sorted({r['ts_code'] for r in (previous_candidates or [])})
    if not codes:
        report.update(status='empty', message='上一交易日没有可复查的尾盘候选')
        return report
    progress('quotes')
    raw = provider.quotes(codes); report['quote_count'] = len(raw)
    diagnostics=getattr(provider,'quote_diagnostics',None)
    if diagnostics:
        report['quote_diagnostics']=diagnostics
        report['warnings'].append(f"本轮有效报价：ProMax {diagnostics['promax_quotes']}只，新浪备用 {diagnostics['sina_quotes']}只；时间来自对应报价记录。")
        if diagnostics['primary_rejected']:
            report['warnings'].append('部分 ProMax 报价不可用或未通过时间/数值校验，已尝试获取完整的备用报价。')
        if diagnostics['fallback_errors']:
            report['warnings'].append(f"备用行情有 {diagnostics['fallback_errors']} 个批次获取失败；未使用无效报价。")
    if getattr(provider, 'conflicting_quotes', 0):
        report['warnings'].append(f"剔除{provider.conflicting_quotes}只存在冲突快照的股票")
    if len(raw) < len(codes):
        report['warnings'].append('部分股票暂无可用快照，结果只覆盖显示的新鲜行情集合')
    now = local_now(); quotes = []
    for r in raw:
        try:
            quotes.append(normalize_quote(r, now))
        except (ValueError, TypeError):
            pass
    report['fresh_count'] = len(quotes);report['generated_at'] = now.timestamp()
    if not quotes or len(quotes) < len(codes) * .90:
        report.update(status='blocked',failure_code='quotes_incomplete',failure_stage='quotes',
                      message=f'同日新鲜行情 {len(quotes)}/{len(codes)}，不足90%，本轮停止筛选')
        return report
    if kind == 'review':
        refs = {r['ts_code']: r for r in (previous_candidates or [])}
        for q in quotes:
            ref = refs[q['ts_code']]
            reference = float(ref['price']);change = (q['close'] / reference - 1) * 100
            report['reviews'].append(dict(ts_code=q['ts_code'], name=ref['name'], price=q['close'], reference_price=reference,
                change=round(change, 3), quote_at=q['quote_at'], note='跌幅达到2%观察线' if change <= -2 else ('涨幅达到3%观察线' if change >= 3 else '距10:00检查截止')))
        report['message'] = '昨日候选早盘复查；参考价是筛选快照，并非持仓成本'
        return report
    if slot_id==report['date']+'-1430':
        baseline=sum(type(f.get('low60')) in [int,float] and math.isfinite(f['low60']) and f['low60']>0 for f in value['features'].values())
        if baseline<len(value['features'])*.90:
            report['bottom_volume']=dict(rule_version=BOTTOM_RULE_VERSION,status='blocked',lookback=60,matched_count=0,candidates=[],checked_at=local_now().timestamp(),
                oldest_quote_at=min(q['quote_at'] for q in quotes),message='近60日低价历史基准未齐，底部放量未执行。')
        else:report['bottom_volume']=bottom_volume_screen(value['features'],quotes,local_now(),value['previous'])
    progress('index')
    try:
        index_raw=provider.index_quote()
        index=normalize_quote(index_raw,local_now(),index=True) if index_raw is not None else None
    except Exception as error:
        index_raw=None;index=None;report['index_failure_type']=type(error).__name__[:80]
    report['index_diagnostics']=getattr(provider,'index_diagnostics',{})
    if index_raw is None:
        report.update(status='blocked',failure_code='index_unavailable',failure_stage='index',
                      message='沪深300主源与备用报价均未通过时间/数值校验，本轮停止筛选')
        if (report.get('bottom_volume') or {}).get('status') in ['ready','empty']:
            report['message']='沪深300报价未通过校验，原两套策略暂停；底部放量已独立完成检查。'
        return report
    report['index_source']=index_raw.get('quote_source','promax')
    if report['index_source']=='sina':report['warnings'].append('沪深300使用新浪备用报价的源站交易时间。')
    report['index_change'] = round(index['change'], 3);report['index_quote_at'] = index['quote_at']
    # The second pass requests minutes only for shortlisted candidates, never 5000 N+1 calls.
    preliminary = screen(value['features'], quotes, index, local_now(), value['previous'])
    minutes = {}
    progress('minutes')
    with ThreadPoolExecutor(max_workers=3) as pool:
        requests={pool.submit(provider.get,'rt_min_daily',ts_code=row['ts_code'],freq='1MIN'):row['ts_code']
                  for row in preliminary['golden'][:10]}
        for future in as_completed(requests):
            try:
                frame=future.result();code=requests[future]
                if not frame.empty and 'ts_code' in frame and set(frame.ts_code)=={code}:
                    minutes[code]=json.loads(frame.to_json(orient='records'))
            except Exception:
                report['warnings'].append('实时分钟接口暂不可用，分时条件保持待核验')
                for pending in requests:pending.cancel()
                break
    progress('validation')
    finished = local_now()
    # Re-check freshness after all network requests, including slow minute requests.
    if any((finished.timestamp() - q['quote_at']) > 180 for q in quotes) or finished.timestamp() - index['quote_at'] > 180:
        report.update(status='blocked',failure_code='quotes_expired',failure_stage='validation',
                      message='采集耗时导致行情过时，停止本轮选股')
        return report
    report['strategies'] = screen(value['features'], quotes, index, finished, value['previous'], minutes)
    report['generated_at'] = finished.timestamp()
    report['warnings'] = sorted(set(report['warnings']))
    report['message'] = '实时规则筛选完成' if index['change'] >= -.3 else '沪深300弱于−0.3%，一夜持股暂停；七步法需核查大盘分时'
    return report


def run(root,cache,kind='screen',previous_candidates=None,provider=None,progress=None,slot_id=None):
    report=_run(root,cache,kind,previous_candidates,provider,progress,slot_id)
    bottom=report.get('bottom_volume')
    if bottom is not None:
        finished=local_now();report['generated_at']=finished.timestamp()
        if finished.timestamp()-bottom['oldest_quote_at']>180:
            report['bottom_volume']=dict(rule_version=BOTTOM_RULE_VERSION,status='blocked',lookback=60,matched_count=0,candidates=[],
                checked_at=finished.timestamp(),oldest_quote_at=bottom['oldest_quote_at'],message='行情在后续采集期间过时，底部放量结果未发布。')
    return report
