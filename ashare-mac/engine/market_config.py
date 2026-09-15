"""Small, non-secret provider settings, also readable by the system-Python API."""
import json
import os
from pathlib import Path

from .datta import DattaError, validate_base_url


def market_configuration():
    value=dict(schema_version=1,provider='datta',base_url='http://127.0.0.1:8080',workers=24,
               primary_provider=None,quote_mode='d101_batch',primary_quote_mode=None)
    override=os.environ.get('GUANLAN_MARKET_PROVIDER')
    specified=os.environ.get('GUANLAN_MARKET_CONFIG')
    path=Path(specified or Path(__file__).resolve().parents[1]/'settings/market-source.json')
    if specified and not path.is_file():raise DattaError('指定的行情来源配置不存在')
    if path.exists():
        if path.stat().st_size>8192:
            raise DattaError('行情来源配置过大')
        try:
            custom=json.loads(path.read_text())
        except (OSError,ValueError):
            raise DattaError('行情来源配置无法读取') from None
        if not isinstance(custom,dict) or set(custom)-set(value):
            raise DattaError('行情来源配置字段无效')
        value.update(custom)
    if override:value['provider']=override
    if type(value['schema_version']) is not int or value['schema_version']!=1 or value['provider']!='datta':
        raise DattaError('行情仅支持达塔，ProMax 已停用，请迁移旧配置')
    if value['primary_provider'] not in [None,'datta']:
        raise DattaError('优先行情来源配置无效')
    if value['quote_mode'] not in ['d6','d101_batch'] or value['primary_quote_mode'] not in [None,'d6','d101_batch']:
        raise DattaError('批量行情配置无效')
    value['base_url']=validate_base_url(value['base_url'])
    if type(value['workers']) is not int or not 1<=value['workers']<=32:
        raise DattaError('行情采集并发配置无效')
    return value


def market_provider_name():
    config=market_configuration();names={'datta':'达塔 D6','promax':'ProMax'}
    if config['primary_provider'] and config['primary_provider']!=config['provider']:
        primary=names[config['primary_provider']]
        if config['primary_provider']=='datta' and config['primary_quote_mode']=='d101_batch':primary='达塔批量初筛＋D6复核'
        return 'Mac：'+primary+'；服务器备用：'+names[config['provider']]
    if config['provider']=='datta' and config['quote_mode']=='d101_batch':return '达塔批量初筛＋D6复核'
    return names[config['provider']]
