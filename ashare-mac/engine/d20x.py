"""Bounded, lease-fenced Datta v95 queries. No persistent paid subscriptions."""
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from .datta import CODE,ZONE,DattaError,DattaUnavailable,number,source_time,unique_object,validate_base_url
from .intraday import local_now,normalize_quote

MAX_FRAME=2*1024*1024


def integer(value,minimum=0):
    if type(value) is not int or value<minimum:raise DattaError('D20x 整数字段无效')
    return value


def event_time(value,day):
    integer(value)
    if value>235959999:raise DattaError('D20x 逐笔时间无效')
    try:return datetime.strptime(day+str(value).zfill(9),'%Y%m%d%H%M%S%f').replace(tzinfo=ZONE)
    except ValueError:raise DattaError('D20x 逐笔时间无效') from None


def decode_recent(trades,observed):
    if not isinstance(trades,list) or len(trades)>100:raise DattaError('D204 分笔数量无效')
    recent={};day=observed.strftime('%Y%m%d')
    for row in trades:
        identity=integer(row['trade_id'],1);clock=event_time(row['time'],day)
        price=integer(row['price'],1)/1000;volume=integer(row['volume'],1)
        if row['side'] not in ['B','S'] or identity in recent:raise DattaError('D204 分笔方向或主键无效')
        if clock.timestamp()>observed.timestamp()+1:raise DattaError('D204 分笔晚于快照')
        recent[identity]=dict(time=row['time'],price=price,volume=volume,side=row['side'],observed_at=clock.timestamp())
    return recent


def latest_stock_trade(trades,observed,quote):
    if not isinstance(trades,list) or len(trades)>100:raise DattaError('D204 缺少可核验成交时间')
    times=[]
    for row in trades:
        try:
            clock=event_time(row['time'],observed.strftime('%Y%m%d'))
            price=integer(row['price'],1)/1000;integer(row['volume'],1)
            if clock.timestamp()>observed.timestamp()+1 or not quote['low']-.001<=price<=quote['high']+.001:continue
            times.append((clock,price))
        except (DattaError,KeyError,TypeError):continue
    if not times:raise DattaError('D204 缺少可核验成交时间')
    _,(clock,price)=max(enumerate(times),key=lambda item:(item[1][0],item[0]))
    if abs(price-quote['close'])>.011:raise DattaError('D204 最近成交与快照价格不一致')
    return clock


def decode_snapshot(item,code,now):
    try:
        if (not CODE.fullmatch(code) or item.get('action')!='once' or item.get('type')!='snapshot'
                or item.get('symbol')!=code.lower() or type(item.get('code')) is not int or item['code']!=0):
            raise DattaError('D204 快照代码或状态不一致')
        stamp=integer(item['datetime']);text=str(stamp)
        if len(text)!=14:raise DattaError('D204 缺少完整行情日期和时间')
        observed=datetime.strptime(text,'%Y%m%d%H%M%S').replace(tzinfo=ZONE)
        mapping=dict(open='open_price',high='high_price',low='low_price',close='last_price',pre_close='prev_close')
        index=code=='000300.SH'
        if index and item.get('stock_type')!='1400':raise DattaError('D204 沪深300类型未通过单位核验')
        # v95 live index values were checked against D101 on 2026-10-08:
        # 433867050 -> 4338.6705; index volume is lots. Stock values differ.
        quote={k:integer(item[v],1)/(100000 if index else 1000) for k,v in mapping.items()}
        quote.update(ts_code=code,name=str(item.get('name') or '')[:30],vol=integer(item['volume'])*(100 if index else 1),
                     amount=number(item['amount']),trade_time=observed.isoformat(),quote_source='datta_d204')
        # v95 refreshes datetime even during lunch. A request-time snapshot
        # must not make an old stock trade pass the 180-second freshness gate.
        traded=observed if index else latest_stock_trade(item.get('recent_trades'),observed,quote)
        quote['trade_time']=traded.isoformat()
        normalize_quote(quote,now,index=index)
        try:recent=decode_recent(item.get('recent_trades',[]),observed)
        except (DattaError,KeyError,TypeError,ValueError):recent={}
        # A malformed optional tape cannot contaminate either the core quote
        # or the evidence. v95 live samples included duplicate IDs/blank sides.
        return dict(quote=quote,date=text[:8],observed_at=traded.timestamp(),snapshot_at=observed.timestamp(),recent_trades=recent,
                    detail_status='verified' if recent else 'unverified')
    except DattaError:raise
    except (KeyError,TypeError,ValueError,AttributeError,OverflowError):
        raise DattaError('D204 快照字段、时间或单位未通过核验') from None


def trade_evidence(item,code,snapshot,now):
    """Only an exact dated D204 event match can date a D203 trade fragment."""
    try:
        if item.get('type')!='trade' or item.get('symbol')!=code[-2:]+code[:6]:
            raise DattaError('D203 逐笔代码不一致')
        rows=item['rows']
        if not isinstance(rows,list) or len(rows)>2048:raise DattaError('D203 逐笔样本过大')
        received_count=len(rows);rows=rows[-20:]
        decimals=integer(item.get('precise',3))
        if decimals>6:raise DattaError('D203 价格精度无效')
        seen=set();matched=[];incomplete=0
        for row in rows:
            if not isinstance(row,dict) or any(k not in row for k in ['trade_no','time','price','volume']):
                incomplete+=1;continue
            identity=integer(row['trade_no'],1);stamp=integer(row['time'])
            if 'seq' in row:integer(row['seq'])
            seconds=len(str(stamp))<=6
            event_time(stamp*1000 if seconds else stamp,snapshot['date'])
            price=integer(row['price'],1)/10**decimals;volume=integer(row['volume'],1)
            flag=row.get('active_flag',0)
            if type(flag) is not int or flag not in [0,1] or identity in seen:
                raise DattaError('D203 逐笔方向或主键无效')
            seen.add(identity);amount=round(price*volume,2)
            if 'amount' in row and abs(number(row['amount'])-amount)>max(1,amount*.005):
                raise DattaError('D203 成交金额单位不一致')
            reference=snapshot['recent_trades'].get(identity)
            if reference is None:continue
            expected_time=reference['time']//1000 if seconds else reference['time']
            if (expected_time!=stamp or abs(reference['price']-price)>1e-6
                    or reference['volume']!=volume or reference['side']!=('B' if flag==0 else 'S')):
                raise DattaError('D203 与有日期的 D204 成交冲突')
            if not -15<=now.timestamp()-reference['observed_at']<=180:continue
            matched.append((flag,amount))
        result=dict(source='datta_d203',status='verified_fragment' if matched else 'unverified_date',
                    sampled_count=len(rows),received_count=received_count,incomplete_count=incomplete,matched_count=len(matched))
        if matched:
            result.update(date=snapshot['date'],sample_buy_amount=round(sum(a for f,a in matched if f==0),2),
                          sample_sell_amount=round(sum(a for f,a in matched if f==1),2))
        return result
    except DattaError:raise
    except (KeyError,TypeError,ValueError,AttributeError,OverflowError):
        raise DattaError('D203 逐笔样本字段无效') from None


class QueryBudget:
    def __init__(self,seconds,limit):
        self.deadline=time.monotonic()+seconds;self.limit=limit;self.bytes=0;self.lock=threading.Lock();self.stop=False

    def account(self,count=0):
        with self.lock:
            self.bytes+=count
            if self.stop:raise DattaUnavailable('D20x 本轮已停止')
            if self.bytes>self.limit or time.monotonic()>self.deadline:raise DattaError('D20x 本轮查询超过用量或时间上限')


class D20xClient:
    provider='datta_d204'

    def __init__(self,base_url='http://127.0.0.1:8080',connector=None,session_check=None,clock=local_now):
        from .datta_session import require_session
        self.base_url=validate_base_url(base_url);self.connector=connector;self.session_check=session_check or require_session
        self.clock=clock;self.diagnostics={}

    def connection(self,channel):
        self.session_check()
        if self.connector is None:
            from websockets.sync.client import connect
            self.connector=connect
        return self.connector('ws'+self.base_url[4:]+'/'+channel,proxy=None,compression=None,
                              open_timeout=4,close_timeout=1,max_size=MAX_FRAME,max_queue=4)

    def receive(self,ws,request,symbol,kind,budget):
        self.session_check();budget.account();ws.send(json.dumps(request))
        deadline=min(budget.deadline,time.monotonic()+5)
        for _ in range(16):
            remaining=deadline-time.monotonic()
            if remaining<=0:raise DattaError('D20x 查询超时')
            raw=ws.recv(timeout=remaining);self.session_check();budget.account(len(raw.encode() if isinstance(raw,str) else raw))
            payload=json.loads(raw,object_pairs_hook=unique_object)
            if (not isinstance(payload,dict) or not isinstance(payload.get('list'),list)
                    or len(payload['list'])>128):raise DattaError('D20x 响应格式无效')
            if not -15<=(self.clock()-source_time(payload['ts'])).total_seconds()<=15:
                raise DattaError('D20x 传输时间过期')
            for item in payload['list']:
                if not isinstance(item,dict):raise DattaError('D20x 响应项目无效')
                status=item.get('code')
                if type(status) is int and status in [405,407]:
                    raise DattaUnavailable('D203/D204 积分不足，请在达塔客户端检查余额' if status==407 else 'D203/D204 登录会话失效')
                if item.get('type')=='error' or (type(status) is int and status>=400):
                    raise DattaError('D20x 通道未返回有效数据')
                if item.get('type')==kind and item.get('symbol')==symbol:
                    if kind=='trade' and 'rows' not in item:continue
                    if kind=='snapshot' and item.get('action')!='once':continue
                    return item
        raise DattaError('D20x 响应缺少请求标的')

    def snapshot(self,code,ws=None,budget=None):
        if not isinstance(code,str) or not CODE.fullmatch(code):raise DattaError('D204 股票代码无效')
        budget=budget or QueryBudget(8,MAX_FRAME)
        if ws is None:
            try:
                with self.connection('d204') as connection:return self.snapshot(code,connection,budget)
            except DattaError:raise
            except Exception:raise DattaError('D204 连接或解析未完成') from None
        item=self.receive(ws,dict(action='once',type='snapshot',symbol=code.lower()),code.lower(),'snapshot',budget)
        return decode_snapshot(item,code,self.clock())

    def quote(self,code):return self.snapshot(code)['quote']

    def quotes(self,codes):
        if (not isinstance(codes,list) or len(codes)>6500 or len(set(codes))!=len(codes)
                or any(not isinstance(c,str) or not CODE.fullmatch(c) for c in codes)):
            raise DattaError('D204 股票集合无效')
        budget=QueryBudget(100,32*1024*1024);started=time.monotonic()
        def collect(chunk):
            rows=[]
            try:
                with self.connection('d204') as ws:
                    for code in chunk:
                        budget.account()
                        try:rows.append(self.snapshot(code,ws,budget)['quote'])
                        except DattaUnavailable:raise
                        except DattaError:continue
                        time.sleep(.01)
            except DattaUnavailable:
                budget.stop=True;raise
            except Exception:pass
            return rows
        with ThreadPoolExecutor(max_workers=2) as pool:
            parts=list(pool.map(collect,[codes[i::2] for i in range(min(2,len(codes)))]))
        rows=[row for part in parts for row in part]
        self.diagnostics=dict(provider=self.provider,requested=len(codes),unavailable=len(codes)-len(rows),
                              payload_bytes=budget.bytes,elapsed_seconds=round(time.monotonic()-started,3))
        return rows

    def trade_sample(self,code,budget=None):
        if not isinstance(code,str) or not CODE.fullmatch(code):raise DattaError('D203 股票代码无效')
        symbol=code[-2:]+code[:6]
        try:
            with self.connection('d203') as ws:
                try:return self.receive(ws,dict(type='trade',code=symbol,enable=1,num=20),symbol,'trade',budget or QueryBudget(6,MAX_FRAME))
                finally:
                    try:ws.send(json.dumps(dict(type='trade',code=symbol,enable=0)))
                    except Exception:pass
        except DattaError:raise
        except Exception:raise DattaError('D203 连接或解析未完成') from None


def enrich_candidates(report,client,clock=local_now):
    """Add bounded fragment observations; never change the screening thresholds."""
    groups=[(report.get(key) or {}).get('candidates',[]) for key in ['orderflow','bottom_volume']]
    groups+=list(report.get('strategies',{}).values())
    rows=[row for group in groups for row in group]
    if not rows:return
    codes=list(dict.fromkeys(row['ts_code'] for row in rows))[:10]
    seconds=min(12,175-(clock().timestamp()-min(row['quote_at'] for row in rows)))
    summary=dict(source='datta_d203_d204',status='skipped',requested=0,verified_count=0,payload_bytes=0)
    report['microstructure']=summary
    if seconds<=0:return
    budget=QueryBudget(seconds,4*1024*1024)
    def fetch(code):
        try:
            budget.account()
            sample=client.trade_sample(code,budget=budget)
            snap=client.snapshot(code,budget=budget)
            return code,trade_evidence(sample,code,snap,clock())
        except DattaUnavailable:
            budget.stop=True;return code,dict(status='unavailable')
        except Exception:return code,dict(status='unavailable')
    with ThreadPoolExecutor(max_workers=2) as pool:observations=dict(pool.map(fetch,codes))
    summary.update(status='complete' if all(e['status']=='verified_fragment' for e in observations.values()) else 'partial',
                   requested=len(codes),verified_count=sum(e['status']=='verified_fragment' for e in observations.values()),
                   payload_bytes=budget.bytes)
    for row in rows:
        evidence=observations.get(row['ts_code'])
        if evidence is None:continue
        if evidence['status']=='verified_fragment':
            line=(f"逐笔样本与有日期行情核对 {evidence['matched_count']} 笔，"
                  f"主买 {evidence['sample_buy_amount']/10000:.2f} 万元、主卖 {evidence['sample_sell_amount']/10000:.2f} 万元")
            if len(row['checks'])<10:row['checks'].append(line)
            pending='D203/D204仅核对近期逐笔片段，不代表全天资金净流入，不单独作为买入条件。'
        elif evidence['status']=='unverified_date':pending='逐笔样本尚未与有日期成交记录对齐，未纳入本次已验证证据。'
        else:pending='本轮逐笔辅助核验未完成，保留原有量价规则结论。'
        if len(row['pending'])<10:row['pending'].append(pending)
    report['generated_at']=clock().timestamp()
