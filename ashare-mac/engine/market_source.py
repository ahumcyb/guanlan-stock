"""Datta-only prices and references; historical snapshots remain immutable."""
import pandas as pd
from datetime import timedelta

from .data import FIELDS
from .datta import DattaClient, DattaError, CODE, date_value
from .intraday import local_now, normalize_quote
from .market_config import market_configuration
from .d101_batch import BatchFallback, capture_batch, verify_batch


class DattaMarketProvider:
    name='达塔 D6'

    def __init__(self,reference_factory=None,client=None):
        settings=market_configuration()
        self.client=client or DattaClient(settings['base_url'],settings['workers'])
        self.batch_enabled=settings['quote_mode']=='d101_batch'
        self.batch_base_url=settings['base_url']
        self._basic=None;self._daily={}
        self._refs=pd.DataFrame(columns=['ts_code','trade_date','up_limit','down_limit','float_share'])
        self._factors=pd.DataFrame(columns=FIELDS['adj_factor'])
        self.reference_warning='新增行情仅使用达塔；连续价格因子根据真实前收盘价在本地计算，不是供应商官方复权因子。'
        self.quote_diagnostics={};self.index_diagnostics={}

    def set_history(self,datasets):
        self.history=datasets

    def set_calendar(self,calendar):
        self.open_dates=set(calendar.loc[calendar.is_open==1,'cal_date'])

    def prepare_days(self,dates,known_codes=()):
        if not dates:return
        from .datta_reference import universe, reference_quote, continuous_factors, no_limit_ipo
        for date in dates:date_value(date)
        self._basic=universe(self.client)
        codes=sorted(set(known_codes)|set(self._basic.ts_code))
        if any(not isinstance(code,str) or not CODE.fullmatch(code) for code in codes):
            raise DattaError('股票名录包含无效代码')
        history=getattr(self,'history',None)
        if history is None:raise DattaError('达塔增量更新需要本地历史尺度锚点')
        first=min(dates)
        listing=dict(zip(self._basic.ts_code,self._basic.list_date))
        prior=history['daily'][history['daily'].trade_date<first]
        factors=history['adj_factor'][history['adj_factor'].trade_date<first]
        anchors=prior.merge(factors,on=['ts_code','trade_date'],validate='one_to_one').groupby('ts_code').trade_date.max().to_dict()
        def history_start(code):
            # Re-fetch every intervening bar for a stock whose last usable
            # anchor precedes the market's previous session. Never silently
            # bridge missing traded days as if they were a corporate action.
            anchor=anchors.get(code)
            if anchor:return (date_value(anchor)+timedelta(days=1)).strftime('%Y%m%d')
            listed=listing.get(code)
            if listed and 0<=(date_value(max(dates))-date_value(listed)).days<1200:return listed
            return first
        rows=self.client.collect(codes,lambda code:self.client.history(code,'DAY',history_start(code),max(dates)),budget=900)
        frame=pd.DataFrame(rows,columns=FIELDS['daily'])
        print('达塔日线已采集 · '+str(len(frame))+' 行，继续核验股本与涨跌停价',flush=True)
        self._daily={date:frame[frame.trade_date==date].copy() for date in dates}
        def fetch_reference(code):
            try:
                payload=self.client.transport('/d6/market/v1/stock/fundamentals',{'symbol':code[-2:].lower()+code[:6]})
                day=date_value(payload['data']['marketDate']).strftime('%Y%m%d')
                exempt=no_limit_ipo(code,day,listing.get(code),getattr(self,'open_dates',set()))
                return reference_quote(payload,code,allow_no_limit=exempt)
            except (KeyError,TypeError):raise DattaError('达塔参考行情字段缺失') from None
        refs=self.client.collect(codes,fetch_reference,budget=900)
        missing=sorted(set(codes)-{row['ts_code'] for row in refs})
        if missing:refs.extend(self.client.collect(missing,fetch_reference,budget=120))
        self._refs=pd.DataFrame(refs,columns=['ts_code','trade_date','up_limit','down_limit','float_share'])
        if not self._refs.empty:
            shares=self._refs[['ts_code','trade_date','float_share']].rename(columns={'trade_date':'shares_date'})
            self._basic=self._basic.merge(shares,on='ts_code',how='left',validate='one_to_one')
        self._factors=continuous_factors(frame,prior,factors,listing)

    def fetch(self,api,**params):
        if api=='stock_basic':
            if self._basic is None:
                from .datta_reference import universe
                self._basic=universe(self.client)
            return self._basic.copy()
        date=params.get('trade_date')
        if api in ['daily','adj_factor','stk_limit','daily_basic']:
            date_value(date)
            if api=='daily':
                if date not in self._daily:raise DattaError('日线尚未完成达塔采集')
                return self._daily[date].copy()
            table=self._factors if api=='adj_factor' else self._refs
            result=table[table.trade_date==date].copy()
            if result.empty:raise DattaError('达塔缺少该交易日的'+api+'，不使用其他行情源')
            columns={'adj_factor':FIELDS['adj_factor'],'stk_limit':FIELDS['stk_limit'],
                     'daily_basic':['ts_code','trade_date','float_share']}[api]
            return result[columns]
        raise DattaError('达塔暂未提供此参考数据，请检查本地已验证数据：'+api)

    def fetch_factors(self,date,codes):
        return self.fetch('adj_factor',trade_date=date)

    def get(self,api,**params):
        if api=='rt_min_daily':
            if params.get('freq')!='1MIN':raise DattaError('盘中策略仅使用1分钟行情')
            date=local_now().strftime('%Y%m%d')
            rows=self.client.history(params['ts_code'],'MIN1',date,date)
            cutoff=local_now().isoformat()
            return pd.DataFrame([row for row in rows if row['time']<=cutoff])
        return self.fetch(api,**params)

    def quotes(self,codes):
        rows=self.client.quotes(codes);now=local_now();valid=[]
        for row in rows:
            try:normalize_quote(row,now)
            except (ValueError,TypeError):continue
            valid.append(row)
        self.quote_diagnostics=dict(self.client.diagnostics,datta_quotes=len(valid),
                                    unavailable=len(codes)-len(valid))
        return valid

    def screen_quotes(self,features,include_bottom):
        codes=sorted(features);now=local_now()
        try:
            from .datta_session import require_session
            require_session()
            capture=capture_batch(self.batch_base_url,codes,now.strftime('%Y%m%d'))
            rows,diagnostics=verify_batch(capture,codes,features,self.client,local_now(),include_bottom,clock=local_now)
            self.quote_diagnostics=dict(diagnostics,datta_quotes=len(rows))
            return rows
        except (BatchFallback,DattaError) as error:
            # Keep the proven full-universe path available when batch data cannot
            # be trusted. Never attach receipt time to an unverified candidate.
            reason=str(error) if isinstance(error,BatchFallback) else 'd6_verification_unavailable'
            rows=self.quotes(codes)
            self.quote_diagnostics.update(mode='d6_fallback',batch_fallback_reason=reason)
            return rows

    def index_quote(self,code='000300.SH'):
        if code!='000300.SH':raise DattaError('盘中策略仅使用沪深300指数')
        row=self.client.quote(code)
        normalize_quote(row,local_now(),index=True)
        self.index_diagnostics=dict(provider='datta_d6',datta_quotes=1)
        return row


def make_daily_provider(reference_factory=None):
    return DattaMarketProvider()


def make_intraday_provider():
    return DattaMarketProvider()
