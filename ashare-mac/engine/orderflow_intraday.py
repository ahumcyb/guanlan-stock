"""14:30 dated large-flow observation, independent of the closing replay rule."""
import time
from concurrent.futures import ThreadPoolExecutor,as_completed
from .datta import DattaClient,DattaError
from .intraday import local_now,finite,MAX_AGE
from .orderflow import decode_flow,flow_pass

POOL_LIMIT=100

def flow_pool(features,quotes,previous,wide=False):
    ranked=[(c,f) for c,f in features.items() if f.get("date")==previous and f.get("adjusted") is True
            and isinstance(f.get("amount20"),(int,float)) and f["amount20"]>=1e8 and f.get("observations",0)>=60
            and not any(mark in str(f.get("name","")).upper() for mark in ["ST","退"])]
    universe={c for c,_ in sorted(ranked,key=lambda p:(-p[1]["amount20"],p[0]))[:POOL_LIMIT]}
    selected=[]
    for q in quotes:
        code=q.get('ts_code');f=features.get(code,{})
        if code not in universe:continue
        try:
            if f.get('date')!=previous or f.get('adjusted') is not True or f.get('observations',0)<60:continue
            if any('ST' in str(n).upper() or '退' in str(n) for n in [f.get('name'),q.get('name')]):continue
            close=finite(q['close'],True);pre=finite(q['pre_close'],True);vol=finite(q['vol'],True);amount=finite(q['amount'],True)
            average=finite(f['amount20'],True);ma=(finite(f['sum19'],True)+close)/20
            position=(close-q['low'])/(q['high']-q['low']) if q['high']>q['low'] else 0
            if (close<3 or average<1e8 or abs(pre/f['last_close']-1)>.003
                    or not (0 if wide else .003)<=close/pre-1<=(.055 if wide else .05)
                    or not (-.01 if wide else 0)<=close/ma-1<=(.09 if wide else .08) or position<(.55 if wide else .65)
                    or not (.9 if wide else 1)<=vol/f['mean_volume5']<=(3.2 if wide else 3)
                    or close<amount/vol*(.995 if wide else 1)):continue
            selected.append((code,average))
        except (ValueError,KeyError,TypeError,ZeroDivisionError):continue
    return [code for code,_ in sorted(selected,key=lambda p:(-p[1],p[0]))[:POOL_LIMIT]]


def run_flow(features,quotes,dates,previous,client=None,clock=local_now,budget=45):
    now=clock();codes=flow_pool(features,quotes,previous);by_code={q['ts_code']:q for q in quotes}
    client=client or DattaClient(workers=4);evidence={};failed=[];started=time.monotonic()
    def fetch(code):
        q=by_code[code];bar=dict(q,trade_date=now.strftime('%Y%m%d'),amount=q['amount']/1000,vol=q['vol']/100)
        params=dict(symbol=code[:6],market=code[-2:].lower())
        history=client.transport('/d6/market/v1/capital/flow/history',dict(params,limit=10))
        raw=client.transport('/d6/market/v1/capital/flow/snapshot',params)
        return decode_flow(raw,history,bar,dates,now=clock())
    with ThreadPoolExecutor(max_workers=4) as pool:
        for offset in range(0,len(codes),4):
            if time.monotonic()-started>budget:failed.extend(codes[offset:]);break
            futures={pool.submit(fetch,code):code for code in codes[offset:offset+4]}
            for future in as_completed(futures):
                code=futures[future]
                try:evidence[code]=future.result()
                except Exception:failed.append(code)  # Isolate provider transport/schema failures from other strategies.
    finished=clock();rows=[]
    oldest=min([by_code[c]['quote_at'] for c in codes]+[e['flow_observed_at'] for e in evidence.values()]+[finished.timestamp()])
    baseline=sum(isinstance(f.get("amount20"),(int,float)) and f["amount20"]>0 for f in features.values())>=len(features)*.90 and bool(features)
    complete=baseline and not failed and -15<=finished.timestamp()-oldest<=MAX_AGE
    if complete:
        for code in codes:
            e=evidence[code]
            if not flow_pass(e):continue
            q=by_code[code];f=features[code];multiple=q['vol']/f['mean_volume5']
            rows.append(dict(strategy='orderflow',ts_code=code,name=f['name'],price=q['close'],change=q['change'],
                quote_at=q['quote_at'],time_basis=q['time_basis'],volume_multiple=multiple,volume_ratio=multiple*240/210,
                vwap=q['amount']/q['vol'],reference_date=previous,state='盘中大单承接观察',
                flow_net_ratio=e['flow_net_ratio'],flow_net=e['flow_net'],flow_net3=e['flow_net3'],
                flow_positive_days=e['flow_positive_days'],flow_observed_at=e['flow_observed_at'],
                checks=['大单净流入≥2000万元且占累计成交额≥3%','含当日的三个交易日至少两日净流入且合计为正',
                        '上涨0.3%–5%，位于MA20上方0%–8%','累计量为前5日均量1–3倍，价格不低于日内均价'],
                pending=['盘中观察，展示实际采集时间，未使用收盘数据','资金流分类估算，不代表机构身份；公告风险需核查']))
        rows.sort(key=lambda r:(-r['flow_net_ratio'],r['ts_code']))
    return dict(rule_version=1,status=('ready' if rows else 'empty') if complete else 'blocked',
        requested=len(codes),verified=len(evidence),matched_count=len(rows),candidates=rows[:10],
        checked_at=finished.timestamp(),oldest_quote_at=oldest,
        message=f'14:30大单资金流核验 {len(evidence)}/{len(codes)}；'+('限定股票池检查完成。' if complete else '数据不完整或过时，未生成候选。'))
