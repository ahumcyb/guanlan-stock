"""Complete, timestamped fallback snapshots from Sina's fixed HTTPS quote host.

No ProMax credential is passed here. Prices and source timestamps always come
from the same record; this adapter never synthesizes a trading timestamp.
"""
import csv
import re
from urllib.request import Request, build_opener, HTTPRedirectHandler
from .intraday import CODE, timestamp

MAX_BATCH=200
MAX_BYTES=2*1024*1024


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


def checked_codes(codes):
    if (not isinstance(codes,list) or not 1<=len(codes)<=MAX_BATCH or len(set(codes))!=len(codes)
            or any(not isinstance(code,str) or not CODE.fullmatch(code) for code in codes)):
        raise ValueError('备用行情股票集合无效')
    return set(codes)


def parse_quotes(body,codes):
    wanted=checked_codes(codes)
    if not isinstance(body,bytes) or len(body)>MAX_BYTES:raise ValueError('备用行情响应过大')
    rows=[];seen=set()
    for line in body.decode('gb18030').splitlines():
        if not line.strip():continue
        match=re.fullmatch(r'var hq_str_(sh|sz)(\d{6})="(.*)";',line.strip())
        if not match:raise ValueError('备用行情响应格式无效')
        code=match[2]+'.'+match[1].upper()
        if code not in wanted or code in seen:raise ValueError('备用行情股票集合不一致')
        seen.add(code)
        if not match[3]:continue  # No quote for this requested symbol.
        fields=next(csv.reader([match[3]]))
        if not 32<=len(fields)<=64:raise ValueError('备用行情字段不完整')
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',fields[30]) or not re.fullmatch(r'\d{2}:\d{2}:\d{2}',fields[31]):
            raise ValueError('备用行情缺少源站交易时间')
        trade_time=fields[30]+' '+fields[31];timestamp(trade_time)
        rows.append(dict(ts_code=code,name=fields[0],open=fields[1],pre_close=fields[2],close=fields[3],
            high=fields[4],low=fields[5],vol=fields[8],amount=fields[9],trade_time=trade_time,quote_source='sina'))
    return rows


def fetch_quotes(codes):
    checked_codes(codes)
    symbols=','.join(code[-2:].lower()+code[:6] for code in codes)
    request=Request('https://hq.sinajs.cn/list='+symbols,
        headers={'Referer':'https://finance.sina.com.cn/','User-Agent':'Mozilla/5.0'})
    with build_opener(NoRedirect()).open(request,timeout=6) as response:
        body=response.read(MAX_BYTES+1)
    return parse_quotes(body,codes)
