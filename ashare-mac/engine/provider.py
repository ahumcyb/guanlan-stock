"""The documented ProMax GET interface. Secrets never enter logs or URLs."""
import getpass
import json
import os
import re
import subprocess
import time
import threading
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler

import pandas as pd

BASE_URL = 'https://pcd.mobcvb.cn/tushare/pro'
ALLOWED = {'daily', 'adj_factor', 'stk_limit', 'stock_basic', 'trade_cal'}
PAGE_SIZE = 5000
FACTOR_PAGE_SIZE = 1000
_REQUEST_LOCK = threading.Lock()
_NEXT_REQUEST_AT = 0.0
_REQUEST_INTERVAL = 2.1


class ProMaxRowLimit(ValueError):
    """A positively identified provider row-budget rejection, never an auth error."""
    pass


class ProMaxUnavailable(ValueError):
    """A completed HTTP 503 response; excludes authentication and rate limits."""
    pass


def parse_response(payload: dict) -> pd.DataFrame:
    if not isinstance(payload, dict) or payload.get('code') != 0:
        raise ValueError('ProMax 返回错误状态')
    data = payload.get('data')
    if not isinstance(data, dict) or not isinstance(data.get('fields'), list) or not isinstance(data.get('items'), list):
        raise ValueError('ProMax 返回格式无效')
    fields, items = data['fields'], data['items']
    if len(fields) != len(set(fields)) or any(not isinstance(r, list) or len(r) != len(fields) for r in items):
        raise ValueError('ProMax 返回列结构无效')
    if 'count' in payload and payload['count'] != len(items):
        raise ValueError('ProMax 返回数量不一致，可能被截断')
    return pd.DataFrame(items, columns=fields)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class ProMax:
    def __init__(self):
        raise ValueError('ProMax 已停用；请使用达塔行情接口')

    @staticmethod
    def _throttle():
        global _NEXT_REQUEST_AT
        with _REQUEST_LOCK:
            delay = max(0.0, _NEXT_REQUEST_AT - time.monotonic())
            if delay:
                time.sleep(delay)
            _NEXT_REQUEST_AT = time.monotonic() + _REQUEST_INTERVAL

    def _page(self, api: str, params: dict) -> pd.DataFrame:
        request = Request(f'{BASE_URL}/{api}?{urlencode(params)}', method='GET',
                          headers={'X-API-Key': self._secret, 'Accept': 'application/json'})
        for attempt in range(3):
            retry_delay = 1 + attempt * 2
            self._throttle()
            try:
                with build_opener(NoRedirect()).open(request, timeout=25) as response:
                    body = response.read(32 * 1024 * 1024 + 1)
                if len(body) > 32 * 1024 * 1024 or self._secret.encode() in body:
                    raise ValueError('ProMax 返回内容未通过安全校验')
                try:
                    return parse_response(json.loads(body))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    raise ValueError('ProMax 返回非 JSON 内容') from None
            except HTTPError as e:
                retry_after = (e.headers or {}).get('Retry-After', '')
                if e.code in (429,500,502,503,504) and re.fullmatch(r'[0-9]{1,4}', str(retry_after)):
                    if int(retry_after)>60:
                        raise ValueError('ProMax 要求较长等待，本轮停止并保留旧数据') from None
                    retry_delay = max(retry_delay, int(retry_after))
                if e.code == 400:
                    try:
                        rejected = e.read(4097)
                        message = json.loads(rejected).get('message') if len(rejected) <= 4096 and self._secret.encode() not in rejected else None
                    except (ValueError, OSError, AttributeError):
                        message = None
                    if message in ['response row count exceeds the limit', 'row count exceeds limit',
                                   f'{api} limit exceeds the request limit']:
                        raise ProMaxRowLimit('ProMax 单次请求或返回行数超限') from None
                if e.code not in (429, 500, 502, 503, 504) or attempt == 2:
                    if e.code==503:
                        raise ProMaxUnavailable('ProMax 上游数据服务暂不可用') from None
                    raise ValueError(f'ProMax HTTP {e.code}，请检查接口权限或稍后重试') from None
            except (URLError, TimeoutError, OSError):
                if attempt == 2:
                    raise ValueError('ProMax 网络连接失败或超时') from None
            time.sleep(retry_delay)
        raise ValueError('ProMax 请求失败')

    @staticmethod
    def _checked_codes(codes):
        if isinstance(codes, str):
            raise ValueError('已知股票集合无效')
        values = list(codes)
        if len(values) > 6500 or any(not isinstance(code, str) or not re.fullmatch(r'\d{6}\.(SH|SZ|BJ)', code) for code in values):
            raise ValueError('已知股票集合无效')
        return tuple(sorted(set(values)))

    def set_known_codes(self, codes):
        self._known_codes = self._checked_codes(codes)

    def fetch_factors(self, date, codes):
        if not isinstance(date,str) or not re.fullmatch(r'\d{8}',date):
            raise ValueError('复权因子日期无效')
        time.strptime(date, '%Y%m%d')
        return self._factor_batches({'trade_date':date},self._checked_codes(codes))

    def _factor_batches(self, params, codes=None):
        codes = self._known_codes if codes is None else codes
        frames = []
        for index in range(0, len(codes), 100):
            batch = codes[index:index+100]
            try:
                page = self._page('adj_factor', dict(params, ts_code=','.join(batch), limit=FACTOR_PAGE_SIZE))
            except ProMaxUnavailable:
                page = self._page('adj_factor', dict(ts_code=','.join(batch),start_date=params['trade_date'],
                                                   end_date=params['trade_date'],limit=FACTOR_PAGE_SIZE))
            if len(page) >= FACTOR_PAGE_SIZE:
                raise ValueError('ProMax 因子分批仍可能截断，停止更新')
            if page.empty:
                continue
            if not {'ts_code', 'trade_date', 'adj_factor'}.issubset(page.columns):
                raise ValueError('ProMax 因子分批缺少字段')
            if not set(page.ts_code).issubset(batch) or not page.trade_date.eq(params['trade_date']).all():
                raise ValueError('ProMax 因子分批代码或日期不一致')
            frames.append(page)
        if not frames:
            return pd.DataFrame(columns=['ts_code', 'trade_date', 'adj_factor'])
        result = pd.concat(frames, ignore_index=True).drop_duplicates().reset_index(drop=True)
        if result.duplicated(['ts_code', 'trade_date']).any():
            raise ValueError('ProMax 因子分批存在冲突，停止更新')
        return result

    def fetch(self, api: str, **params) -> pd.DataFrame:
        # Full-day factors exceed this proxy's row budget and its offset
        # behavior is not reliable. Use the explicitly known source universe.
        # A failed chunk still aborts the entire result, including auth errors.
        if (api == 'adj_factor' and set(params) == {'trade_date'}
                and re.fullmatch(r'\d{8}', str(params['trade_date']))
                and getattr(self, '_known_codes', ())):
            return self._factor_batches(params)
        return self._fetch(api, **params)

    def _fetch(self, api: str, **params) -> pd.DataFrame:
        if api not in ALLOWED:
            raise ValueError('不支持的 ProMax 接口')
        if api=='stock_basic':
            # This reference endpoint rejects limit/offset in this deployment.
            frame=self._page(api,params)
            if frame.empty: return frame
            if 'ts_code' not in frame.columns:
                raise ValueError('ProMax 股票列表缺少主键')
            unique=frame.drop_duplicates().reset_index(drop=True)
            if unique.duplicated(['ts_code']).any():
                raise ValueError('ProMax 股票列表存在冲突记录')
            return unique
        pages = []
        seen=set()
        keys = ['exchange', 'cal_date'] if api == 'trade_cal' else (
            ['ts_code'] if api == 'stock_basic' else ['ts_code', 'trade_date'])
        offset, page_size = 0, PAGE_SIZE
        for _ in range(200):
            try:
                page = self._page(api, dict(params, limit=page_size, offset=offset))
            except ProMaxRowLimit:
                if api == 'adj_factor' or page_size <= 1000:
                    raise
                # Some later pages reject a 5000-row request while the same
                # offset works at 1000; do not change the already-read offset.
                page_size = 1000
                continue
            if len(page) > page_size:
                raise ValueError('ProMax 返回超过请求行数，无法确认分页完整性')
            if page.empty:
                break
            if not set(keys).issubset(page.columns):
                raise ValueError('ProMax 返回缺主键，停止更新')
            page_keys=set(page[keys].itertuples(index=False,name=None))
            if page_keys & seen:
                raise ValueError('ProMax 跨页记录重叠，无法确认分页完整性')
            seen.update(page_keys)
            pages.append(page)
            if len(page) < page_size:
                break
            offset += page_size
            if offset >= 100000:
                raise ValueError('ProMax 分页超过上限')
        else:
            raise ValueError('ProMax 分页超过上限')
        if not pages:
            return pd.DataFrame()
        frame = pd.concat(pages, ignore_index=True)
        if not set(keys).issubset(frame.columns):
            raise ValueError('ProMax 返回缺主键，停止更新')
        # Some ProMax historical partitions contain exact duplicate records.
        # Normalize only identical rows; conflicting key values remain fatal.
        unique = frame.drop_duplicates().reset_index(drop=True)
        if unique.duplicated(keys).any():
            raise ValueError('ProMax 同一主键存在冲突值，停止更新')
        return unique
