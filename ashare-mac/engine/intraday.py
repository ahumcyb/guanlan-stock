"""Deterministic intraday rules. No order placement and no model-generated signals."""
import math
import re
from datetime import datetime
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo('Asia/Shanghai')
SLOTS = {'0910': 'prepare', '1430': 'screen', '1445': 'screen', '1450': 'screen'}
CODE = re.compile(r'^\d{6}\.(SH|SZ)$')
MAX_AGE = 180


def local_now(timestamp=None):
    return datetime.fromtimestamp(timestamp, SHANGHAI) if timestamp is not None else datetime.now(SHANGHAI)


def trading_minutes(now):
    minute = now.hour * 60 + now.minute + now.second / 60
    return min(120, max(0, minute - 570)) + min(120, max(0, minute - 780))


def due_slot(now, open_dates):
    date = now.strftime('%Y%m%d')
    if date not in open_dates:
        return None
    for clock, kind in SLOTS.items():
        start = now.replace(hour=int(clock[:2]), minute=int(clock[2:]), second=0, microsecond=0)
        if 0 <= (now - start).total_seconds() < 180:
            return {'id': date + '-' + clock, 'kind': kind, 'date': date, 'scheduled_at': start.timestamp()}
    return None


def finite(value, positive=False):
    if isinstance(value, bool):
        raise ValueError('行情数值无效')
    result = float(value)
    if not math.isfinite(result) or (positive and result <= 0):
        raise ValueError('行情数值无效')
    return result


def timestamp(value):
    if not isinstance(value, str) or len(value) < 14:
        raise ValueError('行情只有日期，无法确认盘中新鲜度')
    for form in ['%Y%m%d%H%M%S', '%Y-%m-%d %H:%M:%S', '%Y%m%d %H:%M:%S']:
        try:
            return datetime.strptime(value, form).replace(tzinfo=SHANGHAI)
        except ValueError:
            pass
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return result.replace(tzinfo=SHANGHAI) if result.tzinfo is None else result.astimezone(SHANGHAI)
    except ValueError:
        raise ValueError('行情时间无效') from None


def normalize_quote(row, now, index=False):
    code = row.get('ts_code')
    if not isinstance(code, str) or not CODE.fullmatch(code):
        raise ValueError('行情代码无效')
    basis = 'trade_time'
    try:
        observed = timestamp(row.get('trade_time'))
    except ValueError:
        observed = timestamp(row.get('updated_at'))
        basis = 'provider_updated_at'
        trade_date = str(row.get('trade_time') or '').replace('-', '')[:8]
        if trade_date and trade_date != observed.strftime('%Y%m%d'):
            raise ValueError('行情交易日期与更新时间不一致')
    age = (now - observed).total_seconds()
    if observed.date() != now.date() or not -15 <= age <= MAX_AGE:
        raise ValueError('行情已过时或来自未来')
    x = {k: finite(row.get(k), positive=True) for k in ['open', 'high', 'low', 'close', 'pre_close', 'vol', 'amount']}
    if x['high'] + 1e-6 < max(x['open'], x['close'], x['low']) or x['low'] - 1e-6 > min(x['open'], x['close']):
        raise ValueError('实时 OHLC 不一致')
    if not index and not x['low'] * .998 <= x['amount'] / x['vol'] <= x['high'] * 1.002:
        raise ValueError('实时量额单位或均价不一致')
    x.update(ts_code=code, quote_at=observed.timestamp(), quote_time=observed.isoformat(), time_basis=basis,
             name=str(row.get('name') or '')[:30], change=(x['close'] / x['pre_close'] - 1) * 100)
    return x


def minute_pattern(rows, now, quote=None):
    """Verify a late high and a small pullback from a complete 1-minute path."""
    if not isinstance(rows, list) or len(rows) < 200:
        return None
    try:
        bars = sorted([(timestamp(r.get('time')), r) for r in rows], key=lambda b: b[0])
        times = [b[0] for b in bars]
        if len(set(times)) != len(times) or any(t.date() != now.date() or t > now for t in times):
            return None
        if (now - times[-1]).total_seconds() > MAX_AGE or times[0].strftime('%H%M') not in ['0930', '0931']:
            return None
        if any(t.second or t.microsecond for t in times):
            return None
        actual = {t.hour * 60 + t.minute for t in times}; last = max(actual)
        closing_grid = set(range(571, 691)) | set(range(781, last + 1))
        opening_grid = set(range(570, 690)) | set(range(780, last + 1))
        if actual not in [closing_grid, closing_grid | {570}, opening_grid]:
            return None
        volume = amount = 0.0
        high = 0.0
        late_high = None
        for t, r in bars:
            v, a = finite(r['vol']), finite(r['amount'])
            close, top = finite(r['close'], True), finite(r['high'], True)
            if v < 0 or a < 0 or top < close:
                return None
            volume += v; amount += a
            if top > high and '1440' <= t.strftime('%H%M') <= '1448':
                late_high = top
            high = max(high, top)
            if late_high and volume > 0 and close < amount / volume:
                return False
        if not late_high or volume <= 0:
            return False
        if quote is None or not (.90 <= volume / quote['vol'] <= 1.03 and .90 <= amount / quote['amount'] <= 1.03):
            return None
        pullback = (late_high - finite(bars[-1][1]['close'], True)) / late_high * 100
        return 0.05 <= pullback <= 1 and high <= late_high
    except (ValueError, TypeError, KeyError):
        return None


def screen(features, quotes, index, now, expected_previous_date, minutes=None):
    """Features contain only information from the previous completed session."""
    results = {'overnight': [], 'golden': []}
    try:
        index_age = now.timestamp() - finite(index['quote_at'])
        index_ok = (-15 <= index_age <= MAX_AGE and local_now(index['quote_at']).date() == now.date()
                    and finite(index['change']) >= -.3)
    except (ValueError, TypeError, KeyError):
        index_ok = False
    elapsed = trading_minutes(now)
    for q in quotes:
        f = features.get(q['ts_code'])
        if (not f or f.get('date') != expected_previous_date or f.get('observations', 0) < 60
                or f.get('adjusted') is not True or not 3 - 1e-8 <= q['change'] <= 5 + 1e-8):
            continue
        try:
            for field in ['last_close', 'mean_volume5', 'sum4', 'sum9', 'sum19', 'ma5', 'platform_range', 'platform_high']:
                finite(f[field], True)
        except (KeyError, ValueError, TypeError):
            continue
        # An unexpected reference-price adjustment invalidates historical comparisons.
        if abs(q['pre_close'] / f['last_close'] - 1) > .003:
            continue
        if any('ST' in name.upper() or '退' in name for name in [f['name'], q.get('name', '')]):
            continue
        volume_multiple = q['vol'] / f['mean_volume5']
        ratio = volume_multiple * 240 / elapsed if elapsed else 0
        close = q['close']
        ma5 = (f['sum4'] + close) / 5
        ma10 = (f['sum9'] + close) / 10
        ma20 = (f['sum19'] + close) / 20
        trend = close > ma5 > ma10 > ma20 and ma5 > f['ma5']
        platform = f['platform_range'] <= 1.08 and close > f['platform_high']
        common = dict(ts_code=q['ts_code'], name=f['name'], price=round(close, 4), change=round(q['change'], 3),
                      quote_at=q['quote_at'], time_basis=q['time_basis'], volume_multiple=round(volume_multiple, 3),
                      volume_ratio=round(ratio, 3), vwap=round(q['amount'] / q['vol'], 4),
                      reference_date=f['date'], checks=[], pending=['公告、减持及解禁风险需核查'])
        if volume_multiple >= 1.5 and (trend or platform) and index_ok:
            row = dict(common, strategy='overnight', state='正文规则通过',
                       checks=['涨幅 3%–5%', '累计量≥5日均量1.5倍', '均线多头' if trend else '突破10日小平台', '沪深300≥−0.3%'])
            results['overnight'].append(row)
        shares = f.get('float_shares', 0)
        turnover = q['vol'] / shares * 100 if shares > 0 else 0
        capitalization = close * shares / 1e8
        if ratio >= 1 and 5 <= turnover <= 10 and 50 <= capitalization <= 200 and trend:
            pattern = minute_pattern((minutes or {}).get(q['ts_code']), now, q)
            if pattern is False:
                continue
            pending = common['pending'] + ['全天分时强于大盘需核查', '换手与市值按前日流通股本估算']
            if pattern is None:
                pending += ['尾盘新高回踩分时条件待核验']
            results['golden'].append(dict(common, strategy='golden', state='待分时核验' if pattern is None else '分时回踩通过·待复核',
                turnover=round(turnover, 3), market_cap=round(capitalization, 3), pending=pending,
                checks=['涨幅 3%–5%', '量比≥1', '换手 5%–10%（估算）', '流通市值50–200亿（估算）', 'MA5>MA10>MA20且MA5向上'] + (['尾盘新高后回踩不破均价'] if pattern else [])))
    for key in results:
        # Transparent ordering, not a predicted win rate.
        results[key].sort(key=lambda r: (-r['volume_multiple'], abs(r['change'] - 4), r['ts_code']))
        results[key] = results[key][:10]
    return results


def bottom_volume_screen(features,quotes,now,expected_previous_date):
    """Low-zone volume observation, independent of index and 3%-5% change rules."""
    matches=[];observed=[];now=now.astimezone(SHANGHAI)
    for q in quotes:
        code=q.get('ts_code');f=features.get(code)
        if (not isinstance(code,str) or not CODE.fullmatch(code) or not f or f.get('date')!=expected_previous_date
                or f.get('observations',0)<60 or f.get('adjusted') is not True):continue
        if any('ST' in str(name).upper() or '退' in str(name) for name in [f.get('name',''),q.get('name','')]):continue
        try:
            close=finite(q['close'],True);previous=finite(q['pre_close'],True)
            low=finite(f['low60'],True);reference=finite(f['last_close'],True)
            volume=finite(q['vol'],True);average=finite(f['mean_volume5'],True)
            quote_at=finite(q['quote_at']);change=finite(q['change']);vwap=finite(q['amount'],True)/volume
            multiple=finite(volume/average,True)
            if not -15<=now.timestamp()-quote_at<=MAX_AGE or local_now(quote_at).date()!=now.date():continue
            if abs(previous/reference-1)>.003:continue
            observed.append(quote_at);distance=close/low-1
            if multiple<3-1e-8 or not -1e-8<=distance<=.10+1e-8:continue
            finite(vwap,True);elapsed=trading_minutes(now)
            matches.append(dict(strategy='bottom_volume',ts_code=code,name=str(f['name'])[:30],price=round(close,4),change=round(change,3),
                quote_at=quote_at,time_basis=q.get('time_basis','trade_time'),reference_date=expected_previous_date,
                volume_multiple=round(multiple,3),volume_ratio=round(multiple*240/elapsed,3) if elapsed else 0.,vwap=round(vwap,4),
                low60=round(low,6),distance_low60=round(distance,6),state='低位放量观察',
                checks=['现价在近60日最低价上方0%–10%','累计成交量≥前5日全天均量3倍'],
                pending=['低位不等于底部确认，放量可能伴随抛压','公告、减持及解禁风险需核查']))
        except (ValueError,TypeError,KeyError,ZeroDivisionError,OverflowError):continue
    matches.sort(key=lambda row:(-row['volume_multiple'],row['distance_low60'],row['ts_code']))
    return dict(status='ready' if matches else 'empty',lookback=60,matched_count=len(matches),candidates=matches[:10],
                checked_at=now.timestamp(),oldest_quote_at=min(observed) if observed else now.timestamp(),
                message='按放量倍数列出前10只；低位是近60个完整交易日最低价上方0%–10%。')
