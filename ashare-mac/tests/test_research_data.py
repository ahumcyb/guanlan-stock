import unittest
import pandas as pd
from research.acquire import paged, check_limits, check_status, status_span


class ResearchDataTests(unittest.TestCase):
    def test_upstream_cap_is_not_mistaken_for_complete_range(self):
        class Client:
            def _page(self, api, params):
                offset=params['offset']
                return pd.DataFrame({'ts_code':['000001.SZ']*min(2,max(0,5-offset)),
                                     'trade_date':[str(i) for i in range(offset,min(offset+2,5))]})
        x=paged(Client(),'stock_st',{},page_size=2)
        self.assertEqual(len(x),5)

    def test_ignored_offset_is_rejected(self):
        class Client:
            def _page(self, api, params):return pd.DataFrame({'ts_code':['000001.SZ'],'trade_date':['20250506']})
        with self.assertRaises(ValueError):paged(Client(),'stock_st',{},page_size=1)

    def test_missing_history_date_is_not_no_st(self):
        x=pd.DataFrame({'ts_code':['000001.SZ'],'trade_date':['20250506']})
        with self.assertRaises(ValueError):check_status(x,['20250506','20250507'],minimum=1)

    def test_limit_coverage_uses_actual_daily_universe(self):
        x=pd.DataFrame({'ts_code':['000001.SZ'],'trade_date':['20250506'],'up_limit':[11.],'down_limit':[9.]})
        with self.assertRaises(ValueError):check_limits(x,'20250506',{'000001.SZ','600000.SH'})
        self.assertEqual(len(check_limits(x,'20250506',{'000001.SZ'})),1)

    def test_saturated_st_range_is_split_instead_of_accepting_partial_day(self):
        class Client:
            def _page(self,api,params):
                days=[params['trade_date']] if 'trade_date' in params else ['20250506','20250507']
                rows=[{'ts_code':f'{i:06}.SZ','trade_date':d} for d in days for i in range(20)]
                return pd.DataFrame(rows[:params['limit']])
        result=status_span(Client(),['20250506','20250507'],cap=30)
        self.assertEqual(result.groupby('trade_date').size().to_dict(),{'20250506':20,'20250507':20})
