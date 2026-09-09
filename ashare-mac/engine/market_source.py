"""Route prices to D6 while retaining the existing historical reference tables."""
import pandas as pd

from .data import FIELDS
from .datta import DattaClient, DattaError, CODE, date_value
from .intraday import local_now, normalize_quote
from .market_config import market_configuration
from .provider import ProMax
from .d101_batch import BatchFallback, capture_batch, verify_batch


class DattaMarketProvider:
    name='达塔 D6'

    def __init__(self,reference_factory=ProMax,client=None):
        settings=market_configuration()
        self.client=client or DattaClient(settings['base_url'],settings['workers'])
        self.batch_enabled=settings['quote_mode']=='d101_batch'
        self.batch_base_url=settings['base_url']
        self.reference_factory=reference_factory;self._reference=None;self._basic=None;self._daily={}
        self.quote_diagnostics={};self.index_diagnostics={}

    @property
    def reference(self):
        if self._reference is None:self._reference=self.reference_factory()
        return self._reference

    def prepare_days(self,dates,known_codes=()):
        if not dates:return
        for date in dates:date_value(date)
        self._basic=self.reference.fetch('stock_basic',list_status='L')
        if 'ts_code' not in self._basic or self._basic.ts_code.duplicated().any():
            raise DattaError('参考股票名录缺少有效主键')
        codes=sorted(set(known_codes)|set(self._basic.ts_code))
        if any(not isinstance(code,str) or not CODE.fullmatch(code) for code in codes):
            raise DattaError('参考股票名录包含无效代码')
        rows=self.client.collect(codes,lambda code:self.client.history(code,'DAY',min(dates),max(dates)),budget=900)
        frame=pd.DataFrame(rows,columns=FIELDS['daily'])
        self._daily={date:frame[frame.trade_date==date].copy() for date in dates}

    def fetch(self,api,**params):
        if api=='daily':
            date=params.get('trade_date')
            date_value(date)
            if date not in self._daily:self.prepare_days([date])
            return self._daily[date].copy()
        if api=='stock_basic' and params=={'list_status':'L'} and self._basic is not None:
            return self._basic.copy()
        return self.reference.fetch(api,**params)

    def get(self,api,**params):
        if api=='rt_min_daily':
            if params.get('freq')!='1MIN':raise DattaError('盘中策略仅使用1分钟行情')
            date=local_now().strftime('%Y%m%d')
            rows=self.client.history(params['ts_code'],'MIN1',date,date)
            # A minute sequence may contain a still-forming next bar. Keep only
            # bars already completed at acquisition, preserving its source time.
            cutoff=local_now().isoformat()
            return pd.DataFrame([row for row in rows if row['time']<=cutoff])
        if api=='daily':return self.fetch(api,trade_date=params.get('trade_date'))
        return self.reference.get(api,**params)

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


def make_daily_provider(reference_factory=ProMax):
    return DattaMarketProvider(reference_factory) if market_configuration()['provider']=='datta' else reference_factory()


def make_intraday_provider():
    from .intraday_runner import IntradayProvider
    return DattaMarketProvider(IntradayProvider) if market_configuration()['provider']=='datta' else IntradayProvider()
