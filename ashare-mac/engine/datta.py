"""D6 market data through the customer's loopback DataInterface client."""
import json
import math
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from zoneinfo import ZoneInfo

ZONE = ZoneInfo('Asia/Shanghai')
CODE = re.compile(r'^\d{6}\.(SH|SZ|BJ)$')
MAX_BYTES = 8 * 1024 * 1024


class DattaError(ValueError):
    pass


class DattaUnavailable(DattaError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def validate_base_url(value):
    try:
        parsed = urlsplit(value)
        if (parsed.scheme != 'http' or parsed.hostname not in ['127.0.0.1', '::1']
                or parsed.username is not None or parsed.password is not None
                or parsed.path not in ['', '/'] or parsed.query or parsed.fragment
                or parsed.port is None or not 1 <= parsed.port <= 65535):
            raise ValueError()
    except (TypeError, ValueError):
        raise DattaError('达塔接口必须使用本机 HTTP 地址和端口') from None
    return value.rstrip('/')


def number(value, positive=False):
    if type(value) not in (int, float) or not math.isfinite(value) or (positive and value <= 0):
        raise DattaError('达塔行情数值无效')
    return float(value)


def date_value(value):
    text = str(value)
    if not re.fullmatch(r'\d{8}', text):
        raise DattaError('达塔交易日期无效')
    try:
        return datetime.strptime(text, '%Y%m%d').replace(tzinfo=ZONE)
    except ValueError:
        raise DattaError('达塔交易日期无效') from None


def source_time(value):
    seconds = number(value, True)
    if seconds >= 1e12:
        seconds /= 1000
    if not 946656000 <= seconds < 4102444800:
        raise DattaError('达塔行情时间戳无效')
    return datetime.fromtimestamp(seconds, ZONE)


def check_prices(row):
    if row['high'] < max(row['open'], row['close'], row['low']) or row['low'] > min(row['open'], row['close']):
        raise DattaError('达塔 OHLC 不一致')
    if row['vol'] > 0 and not row['low']*.998 <= row['amount']/row['vol'] <= row['high']*1.002:
        raise DattaError('达塔量额单位或均价不一致')


def decode_quote(payload, code):
    try:
        if not CODE.fullmatch(code) or type(payload.get('code')) is not int or payload['code'] != 0:
            raise DattaError('达塔未返回有效股票行情')
        data = payload['data']
        if data['prodCode'] != code[:6] or data['hqTypeCode'].lower() != code[-2:].lower():
            raise DattaError('达塔返回的股票代码不一致')
        day = date_value(data['marketDate'])
        observed = source_time(data['dataTimestamp'])
        if day.date() != observed.date():
            raise DattaError('达塔行情日期与更新时间不一致')
        fields = dict(open='openPrice', high='highPx', low='lowPx', close='lastPx', pre_close='preClosePx')
        result = {target: number(data[source], True)/1000 for target,source in fields.items()}
        if code != '000300.SH':
            # D6 occasionally truncates a binary float when encoding thousandths
            # (16059 for an A-share price of 16.06). Restore the stock's cent tick.
            result = {key: round(value, 2) for key,value in result.items()}
        result.update(vol=number(data['businessAmount']), amount=number(data['businessBalance']))
        if result['vol'] < 0 or result['amount'] < 0:
            raise DattaError('达塔成交量额无效')
        if code != '000300.SH':
            check_prices(result)
        elif result['high'] < max(result['open'],result['close'],result['low']):
            raise DattaError('达塔指数 OHLC 无效')
        result.update(ts_code=code, name=str(data.get('prodName') or '').strip()[:30],
                      trade_time=day.strftime('%Y%m%d'), updated_at=observed.isoformat(), quote_source='datta')
        return result
    except DattaError:
        raise
    except (KeyError, TypeError, AttributeError, ValueError, OverflowError):
        raise DattaError('达塔股票行情缺少有效字段') from None


def decode_bars(payload, code, period, start, end):
    try:
        first,last = date_value(start),date_value(end)
        if not CODE.fullmatch(code) or period not in ['DAY','MIN1'] or first > last:
            raise DattaError('达塔 K 线请求无效')
        if type(payload.get('Code')) is not int or payload['Code'] != 0:
            raise DattaError('达塔未返回有效 K 线')
        rows = payload['KlineData']
        if not isinstance(rows,list) or len(rows)>1200:
            raise DattaError('达塔 K 线数量或结构无效')
        seen=set();result=[]
        for item in rows:
            day,observed=source_time(item['TradingDay']),source_time(item['Time'])
            if not first.date()<=day.date()<=last.date() or observed.date()!=day.date():
                raise DattaError('达塔返回了请求日期之外的 K 线')
            key=day.strftime('%Y%m%d') if period=='DAY' else observed.timestamp()
            if key in seen:
                raise DattaError('达塔 K 线主键重复')
            seen.add(key)
            row={target:number(item[source],True) for target,source in
                 dict(open='Open',high='High',low='Low',close='Close',pre_close='PreClose').items()}
            row.update(vol=number(item['Volume']),amount=number(item['Amount']))
            if row['vol']<0 or row['amount']<0:
                raise DattaError('达塔 K 线量额无效')
            check_prices(row)
            row['ts_code']=code
            if period=='DAY':
                row.update(trade_date=day.strftime('%Y%m%d'),vol=row['vol']/100,amount=row['amount']/1000)
            else:
                row['time']=observed.isoformat()
            result.append(row)
        return sorted(result,key=lambda row:row.get('trade_date',row.get('time')))
    except DattaError:
        raise
    except (KeyError, TypeError, AttributeError, ValueError, OverflowError):
        raise DattaError('达塔 K 线缺少有效字段') from None


def unique_object(pairs):
    result={}
    for key,value in pairs:
        if key in result:
            raise DattaError('达塔响应字段重复')
        result[key]=value
    return result


class DattaClient:
    def __init__(self, base_url='http://127.0.0.1:8080', workers=16, transport=None):
        self.base_url=validate_base_url(base_url)
        if type(workers) is not int or not 1<=workers<=32:
            raise DattaError('达塔采集并发参数无效')
        self.workers=workers;self.transport=transport or self._request
        self.custom_transport=transport is not None
        self.opener=build_opener(ProxyHandler({}),NoRedirect())
        self.diagnostics={}

    def _request(self,path,params):
        request=Request(self.base_url+path+('?' + urlencode(params) if params else ''),headers={'Accept':'application/json'})
        try:
            with self.opener.open(request,timeout=4) as response:
                body=response.read(MAX_BYTES+1)
        except HTTPError as error:
            if error.code in [401,403]:
                raise DattaUnavailable('达塔 D6 未授权或会话已失效') from None
            raise DattaError('达塔行情 HTTP '+str(error.code)) from None
        except (URLError,TimeoutError,OSError):
            raise DattaError('达塔客户端未连接或请求超时') from None
        try:
            if len(body)>MAX_BYTES:
                raise DattaError('达塔响应超过大小上限')
            return json.loads(body,object_pairs_hook=unique_object)
        except (ValueError,UnicodeError,RecursionError):
            raise DattaError('达塔响应格式无效') from None

    def quote(self,code):
        if not isinstance(code,str) or not CODE.fullmatch(code):
            raise DattaError('达塔股票代码无效')
        payload=self.transport('/d6/market/v1/stock/fundamentals',{'symbol':code[-2:].lower()+code[:6]})
        return decode_quote(payload,code)

    def history(self,code,period,start,end):
        first,last=date_value(start),date_value(end)
        if not isinstance(code,str) or not CODE.fullmatch(code) or period not in ['DAY','MIN1'] or first>last:
            raise DattaError('达塔 K 线请求无效')
        days=(last-first).days+1
        limit=min(1200,max(50,math.ceil((days if period=='DAY' else days*240)/50)*50))
        if days>1200 or (period=='MIN1' and days>5):
            raise DattaError('达塔 K 线请求日期跨度过大')
        params=dict(market=code[-2:],inst=code[:6],period=period,startTime=int(first.timestamp()),
                    endTime=int((last+timedelta(days=1)).timestamp()),limit=limit)
        return decode_bars(self.transport('/d6/market/v1/kline/history',params),code,period,start,end)

    def collect(self,codes,fetch,budget=120):
        if (not isinstance(codes,list) or len(codes)>6500 or len(set(codes))!=len(codes)
                or any(not isinstance(code,str) or not CODE.fullmatch(code) for code in codes)):
            raise DattaError('达塔股票集合无效')
        start=time.monotonic();rows=[];failures=[]
        if not self.custom_transport:
            try:self._request('/d6/market/catalog',{})
            except DattaError:
                raise DattaUnavailable('达塔客户端数据端未连接，请确认客户端已启动并登录') from None
        def bounded(code):
            if time.monotonic()-start>=budget:
                raise DattaError('达塔采集超过本轮时限')
            return fetch(code)
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            futures={pool.submit(bounded,code):code for code in codes}
            for future in as_completed(futures):
                try:
                    value=future.result()
                    if isinstance(value,list):rows.extend(value)
                    else:rows.append(value)
                except DattaUnavailable:
                    for pending in futures:pending.cancel()
                    raise
                except DattaError:
                    failures.append(futures[future])
        self.diagnostics=dict(provider='datta_d6',requested=len(codes),unavailable=len(failures),
                              elapsed_seconds=round(time.monotonic()-start,3))
        return rows

    def quotes(self,codes):
        return self.collect(codes,self.quote)
