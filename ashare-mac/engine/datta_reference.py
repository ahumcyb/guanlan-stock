"""Validated Datta reference data and explicitly derived continuous-price factors."""
import re
import pandas as pd
from .datta import DattaError, date_value, number, source_time


def decode_universe(rows, bse_codes):
    result=[];seen=set()
    for row in rows:
        code=row.get('code','')
        if not isinstance(code,str) or not re.fullmatch(r'(SH|SZ|BJ)\d{6}',code):
            raise DattaError('达塔股票名录代码无效')
        exchange='BJ' if code[2:] in bse_codes else code[:2]
        canonical=code[2:]+'.'+exchange
        if canonical in seen:raise DattaError('达塔股票名录分页重复')
        seen.add(canonical)
        name=row.get('name');industry=row.get('industry_name')
        if not isinstance(name,str) or not name.strip():raise DattaError('达塔股票名称缺失')
        # The vendor includes pre-listing instruments with an explicit zero date.
        # They have no verified listing history and cannot enter the stock pool.
        if row.get('list_date')==0:continue
        listing=date_value(row['list_date']).strftime('%Y%m%d')
        result.append(dict(ts_code=canonical,name=name.strip(),industry=industry or '',list_date=listing))
    return pd.DataFrame(result,columns=['ts_code','name','industry','list_date'])


def universe(client):
    def pages(kind):
        rows=[];total=None
        while total is None or len(rows)<total:
            payload=client.transport('/d4/l1/instrument_list',dict(universe=kind,skip=len(rows),count=500,
                fields='code,name,list_date,industry_name'))
            current=payload.get('total');page=payload.get('rows')
            if (type(current) is not int or not 0<current<=6500 or (total is not None and total!=current)
                    or not isinstance(page,list) or not 0<len(page)<=500):
                raise DattaError('达塔股票名录分页不完整')
            total=current;rows.extend(page)
            if len(rows)>total:raise DattaError('达塔股票名录超过声明数量')
        return rows
    bse=pages('cn_bse_stock');all_rows=pages('cn_hsj_stock')
    bse_codes={row['code'][2:] for row in bse}
    if len(bse_codes)!=len(bse):raise DattaError('达塔北交所名录重复')
    frame=decode_universe(all_rows,bse_codes)
    listed_bse={row['code'][2:] for row in bse if row.get('list_date')!=0}
    if len(frame)<4000 or not listed_bse.issubset(set(frame.ts_code.str[:6])):
        raise DattaError('达塔全市场名录覆盖不足')
    return frame


def no_limit_ipo(code,day,listing,open_dates):
    if listing is None:return False
    age=(date_value(day)-date_value(listing)).days
    if not 0<=age<=14:return False
    if code.endswith('.BJ'):return day==listing and day in open_dates
    if listing not in open_dates or day not in open_dates:return False
    return 1<=sum(listing<=d<=day for d in open_dates)<=5


def reference_quote(payload, code,allow_no_limit=False):
    if payload.get('code')!=0:raise DattaError('达塔参考行情未返回')
    d=payload.get('data',{})
    if d.get('prodCode')!=code[:6] or str(d.get('hqTypeCode','')).upper()!=code[-2:]:
        raise DattaError('达塔参考行情代码不一致')
    day=date_value(d['marketDate']).strftime('%Y%m%d')
    if source_time(d['dataTimestamp']).strftime('%Y%m%d')!=day:
        raise DattaError('达塔参考行情时间不一致')
    up=round(number(d['upPx'])/1000,2);down=round(number(d['downPx'])/1000,2)
    # Explicit vendor 0/0 denotes a no-limit listing session. Preserve it;
    # existing strategy constraints reject those sessions rather than inventing
    # a percentage limit for an IPO.
    if down<0 or up<down or (up==down and up!=0):raise DattaError('达塔涨跌停价无效')
    if up==down==0 and not allow_no_limit:raise DattaError('零涨跌停价未确认属于新股无涨跌幅限制期')
    shares=number(d['circulationAmount'],True);price=number(d['lastPx'],True)/1000
    market=number(d['circulationValue'],True)
    if not .995<=market/(shares*price)<=1.005:raise DattaError('达塔流通股本与市值单位不一致')
    return dict(ts_code=code,trade_date=day,up_limit=up,down_limit=down,float_share=shares/10000)


def continuous_factors(current, previous, factors, listing):
    """Preserve the old scale, advancing only with an observed ex-date pre-close.

    These are locally derived price-continuity factors, not official vendor
    adjustment factors. Missing anchors must fail, except a verified listing day.
    """
    result=[]
    anchors={}
    if not previous.empty and not factors.empty:
        joined=previous.merge(factors,on=['ts_code','trade_date'],validate='one_to_one')
        for row in joined.sort_values('trade_date').itertuples():
            anchors[row.ts_code]=(row.trade_date,float(row.close),float(row.adj_factor))
    for row in current.sort_values(['trade_date','ts_code']).itertuples():
        anchor=anchors.get(row.ts_code)
        if anchor is None:
            if listing.get(row.ts_code)!=row.trade_date:raise DattaError('连续价格缺少历史尺度锚点：'+row.ts_code)
            factor=1.
        else:
            day,close,base=anchor
            if day>=row.trade_date:raise DattaError('连续价格日期未严格递增')
            factor=number(base,True)*number(close,True)/number(float(row.pre_close),True)
        number(factor,True)
        result.append(dict(ts_code=row.ts_code,trade_date=row.trade_date,adj_factor=factor))
        anchors[row.ts_code]=(row.trade_date,float(row.close),factor)
    return pd.DataFrame(result,columns=['ts_code','trade_date','adj_factor'])
