import tempfile
import unittest
from pathlib import Path
import pandas as pd

from engine.data import validate, combine, publish_day, atomic_json, full_market_dates, read_reference
from engine.provider import parse_response, ProMax, PAGE_SIZE


def daily():
    return pd.DataFrame([dict(ts_code='000001.SZ', trade_date='20260904',
                             open=10, high=11, low=9, close=10.5,
                             pre_close=10, vol=1000, amount=10000)])


class DataTests(unittest.TestCase):
    def test_duplicate_prices_rejected(self):
        with self.assertRaises(ValueError):
            validate(pd.concat([daily(), daily()]), 'daily')

    def test_impossible_candle_rejected(self):
        x = daily(); x.loc[0, 'high'] = 9
        with self.assertRaises(ValueError):
            validate(x, 'daily')

    def test_malformed_day_rejected(self):
        x = daily(); x.loc[0, 'trade_date'] = '20260230'
        with self.assertRaises(ValueError):
            validate(x, 'daily')

    def test_identical_overlap_deduplicates(self):
        self.assertEqual(len(combine([daily(), daily()], 'daily')), 1)

    def test_conflicting_overlap_rejected(self):
        x = daily(); x.loc[0, 'close'] = 10.6
        with self.assertRaises(ValueError):
            combine([daily(), x], 'daily')

    def test_failed_publication_keeps_previous_day(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            adj = daily()[['ts_code', 'trade_date']].assign(adj_factor=1.)
            lim = daily()[['ts_code', 'trade_date']].assign(up_limit=11., down_limit=9.)
            publish_day(root, '20260904', {'daily': daily(), 'adj_factor': adj, 'stk_limit': lim})
            before = (root/'20260904'/'daily.parquet').read_bytes()
            with self.assertRaises(ValueError):
                publish_day(root, '20260904', {'daily': daily(), 'adj_factor': adj.iloc[:0], 'stk_limit': lim})
            self.assertEqual(before, (root/'20260904'/'daily.parquet').read_bytes())

    def test_truncated_api_result_rejected(self):
        with self.assertRaises(ValueError):
            parse_response({'code': 0, 'count': 2, 'data': {'fields': ['a'], 'items': [[1]]}})

    def test_provider_errors_do_not_echo_payload(self):
        with self.assertRaisesRegex(ValueError, '^ProMax 返回错误状态$'):
            parse_response({'code': 401, 'msg': 'secret-should-never-be-echoed'})

    def test_identical_provider_duplicates_can_be_normalized(self):
        class Fake(ProMax):
            def __init__(self): pass
            def _page(self, api, params): return pd.concat([daily(),daily()],ignore_index=True)
        self.assertEqual(len(Fake().fetch('daily')),1)

    def test_provider_conflicting_duplicates_are_rejected(self):
        x=daily(); x.loc[0,'close']=10.7
        class Fake(ProMax):
            def __init__(self): pass
            def _page(self, api, params): return pd.concat([daily(),x],ignore_index=True)
        with self.assertRaises(ValueError): Fake().fetch('daily')

    def test_existing_partition_rejects_superset_retry(self):
        with tempfile.TemporaryDirectory() as d:
            one = daily()
            def bundle(frame):
                return {'daily':frame,'adj_factor':frame[ ['ts_code','trade_date'] ].assign(adj_factor=1.),
                        'stk_limit':frame[ ['ts_code','trade_date'] ].assign(up_limit=11.,down_limit=9.)}
            publish_day(Path(d),'20260904',bundle(one))
            two=one.copy(); two['ts_code']='000002.SZ'
            with self.assertRaises(ValueError):
                publish_day(Path(d),'20260904',bundle(pd.concat([one,two],ignore_index=True)))

    def test_nonprogressing_second_page_rejected(self):
        page=pd.concat([daily()]*PAGE_SIZE,ignore_index=True)
        page['ts_code']=[f'{i:06d}.SZ' for i in range(PAGE_SIZE)]
        class Fake(ProMax):
            def __init__(self): pass
            def _page(self, api, params): return page if params['offset']==0 else page.iloc[:50]
        with self.assertRaises(ValueError): Fake().fetch('daily')

    def test_invalid_report_json_does_not_replace_previous_pointer(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'current.json'
            atomic_json(path,{'generation':'old'})
            before=path.read_bytes()
            with self.assertRaises(ValueError): atomic_json(path,{'value':float('nan')})
            self.assertEqual(path.read_bytes(),before)
            self.assertEqual(len(list(Path(d).iterdir())),1)

    def test_stock_basic_uses_supported_unpaginated_reference_query(self):
        class Fake(ProMax):
            def __init__(self): pass
            def _page(self,api,params):
                if 'offset' in params or 'limit' in params: raise ValueError('reference API does not accept pagination')
                return pd.DataFrame({'ts_code':['000001.SZ'],'name':['测试']})
        self.assertEqual(len(Fake().fetch('stock_basic',list_status='L')),1)

    def test_partial_existing_latest_session_is_not_complete(self):
        days=pd.bdate_range('20260101',periods=11).strftime('%Y%m%d')
        counts=pd.Series([5550]*10+[4500],index=days)
        self.assertNotIn(days[-1],full_market_dates(counts))

    def test_numeric_provider_listing_dates_are_normalized_before_join(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); (root/'raw').mkdir()
            pd.DataFrame({'ts_code':['000001.SZ'],'list_date':[19910403]}).to_parquet(root/'raw'/'stock_basic.parquet',index=False)
            result=read_reference(root,root/'overlay','stock_basic')
            self.assertEqual(result.iloc[0].list_date,'19910403')


if __name__ == '__main__':
    unittest.main()
