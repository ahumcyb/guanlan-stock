"""The documented ProMax GET interface. Secrets never enter logs or URLs."""
import getpass
import json
import os
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler

import pandas as pd

BASE_URL = 'https://pcd.mobcvb.cn/tushare/pro'
ALLOWED = {'daily', 'adj_factor', 'stk_limit', 'stock_basic', 'trade_cal'}


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
        secret = os.environ.get('PROMAX_API_KEY', '').strip()
        if not secret:
            p = subprocess.run(['/usr/bin/security', 'find-generic-password', '-s',
                                'quanta.promax.api-key', '-a', getpass.getuser(), '-w'],
                               capture_output=True, text=True, timeout=10)
            if p.returncode == 0:
                secret = p.stdout.strip()
        if not secret or not secret.isascii() or not all(32 < ord(c) < 127 for c in secret):
            raise ValueError('找不到 ProMax 凭据，请在钥匙串配置 quanta.promax.api-key')
        self._secret = secret

    def _page(self, api: str, params: dict) -> pd.DataFrame:
        request = Request(f'{BASE_URL}/{api}?{urlencode(params)}', method='GET',
                          headers={'X-API-Key': self._secret, 'Accept': 'application/json'})
        for attempt in range(3):
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
                if e.code not in (429, 500, 502, 503, 504) or attempt == 2:
                    raise ValueError(f'ProMax HTTP {e.code}，请检查接口权限或稍后重试') from None
            except (URLError, TimeoutError, OSError):
                if attempt == 2:
                    raise ValueError('ProMax 网络连接失败或超时') from None
            time.sleep(1 + attempt * 2)
        raise ValueError('ProMax 请求失败')

    def fetch(self, api: str, **params) -> pd.DataFrame:
        if api not in ALLOWED:
            raise ValueError('不支持的 ProMax 接口')
        pages = []
        seen=set()
        keys = ['exchange', 'cal_date'] if api == 'trade_cal' else (
            ['ts_code'] if api == 'stock_basic' else ['ts_code', 'trade_date'])
        for offset in range(0, 100000, 5000):
            page = self._page(api, dict(params, limit=5000, offset=offset))
            if page.empty:
                break
            if not set(keys).issubset(page.columns):
                raise ValueError('ProMax 返回缺主键，停止更新')
            page_keys=set(page[keys].itertuples(index=False,name=None))
            if page_keys & seen:
                raise ValueError('ProMax 跨页记录重叠，无法确认分页完整性')
            seen.update(page_keys)
            pages.append(page)
            if len(page) < 5000:
                break
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
