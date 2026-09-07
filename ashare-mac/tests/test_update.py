import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import pandas as pd
from engine.update import update, validate_reference, load_calendar


class UpdateTests(unittest.TestCase):
    def test_complete_local_calendar_does_not_depend_on_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'source'; (root/'raw').mkdir(parents=True)
            days=pd.date_range('20260101','20261231').strftime('%Y%m%d')
            pd.DataFrame(dict(exchange='SSE',cal_date=days,is_open=0)).to_parquet(root/'raw'/'trade_cal.parquet',index=False)
            class Offline:
                def fetch(self,*args,**kwargs): raise AssertionError('unnecessary network request')
            result=load_calendar(root,Path(tmp)/'overlay','20260101','20261231',Offline())
            self.assertEqual(len(result),365)

    def test_truncated_reference_cannot_replace_complete_snapshot(self):
        previous=pd.DataFrame({'ts_code':[f'{i:06d}.SZ' for i in range(5500)]})
        new=previous.iloc[:4500].assign(name='测试',industry='行业',list_date='20000101')
        with self.assertRaises(ValueError): validate_reference(new,previous)

    def test_sparse_calendar_cannot_replace_year(self):
        calendar=pd.DataFrame({'exchange':['SSE','SSE'],'cal_date':['20250101','20261231'],'is_open':[0,0]})
        from engine.update import validate_calendar
        with self.assertRaises(ValueError): validate_calendar(calendar,'20250101','20261231')

    def test_reference_failure_preserves_finished_update_audit(self):
        codes=[f'{i:06d}.SZ' for i in range(4001)]
        keys=pd.DataFrame(dict(ts_code=codes,trade_date='20260904'))
        frames={'daily':keys.assign(open=10.,high=11.,low=9.,close=10.,pre_close=10.,vol=100.,amount=100000.),
                'adj_factor':keys.assign(adj_factor=1.),'stk_limit':keys.assign(up_limit=11.,down_limit=9.)}
        class Fake:
            def fetch(self,api,**params):
                if api=='trade_cal':
                    days=pd.date_range('20250101','20261231').strftime('%Y%m%d')
                    calendar=pd.DataFrame(dict(exchange='SSE',cal_date=days,is_open=[int(d=='20260904') for d in days]))
                    return calendar[calendar.is_open==params['is_open']].reset_index(drop=True)
                raise ValueError('ProMax 返回错误状态')
        with tempfile.TemporaryDirectory() as tmp, patch('engine.update.ProMax',return_value=Fake()), patch('engine.update.read_dataset',side_effect=lambda r,o,k:frames[k]):
            result=update(Path(tmp)/'source',Path(tmp)/'overlay',through='20260904')
            self.assertEqual(result['validation'],'partial')
            self.assertEqual(result['failures'][0]['date'],'stock_basic')
            self.assertTrue((Path(tmp)/'overlay'/'last_update.json').exists())

    def test_closing_refresh_reloads_a_complete_day_and_binds_actual_new_values(self):
        from tests.test_close_proof import frames, DATE, NOW
        from engine.close_proof import verify_attestation
        local=frames();remote={k:v.copy() for k,v in local.items()};remote['daily']['close']=10.1
        calls=[]
        class Fake:
            def fetch(self,api,**params):
                if api=='trade_cal':
                    days=pd.date_range('20250101','20261231').strftime('%Y%m%d')
                    table=pd.DataFrame(dict(exchange='SSE',cal_date=days,is_open=[int(d==DATE) for d in days]))
                    return table[table.is_open==params['is_open']].reset_index(drop=True)
                if api=='stock_basic':return local['daily'][['ts_code']].assign(name='测试',industry='行业',list_date='20000101')
                calls.append(api);return remote[api].copy()
        with tempfile.TemporaryDirectory() as tmp,patch('engine.update.ProMax',return_value=Fake()),patch('engine.update.read_dataset',side_effect=lambda r,o,k:local[k]),patch('engine.update.datetime') as clock:
            clock.now.return_value=NOW
            result=update(Path(tmp)/'source',Path(tmp)/'overlay',through=DATE,force_latest=True)
            self.assertEqual(set(calls),{'daily','adj_factor','stk_limit'})
            self.assertEqual(len(calls),3)
            self.assertEqual(result['forced_latest_date'],DATE)
            verify_attestation(result['close_attestation'],DATE,remote,NOW)

    def test_failed_forced_day_cannot_attest_the_old_complete_snapshot(self):
        from tests.test_close_proof import frames, DATE, NOW
        local=frames()
        class Fake:
            def fetch(self,api,**params):
                if api=='trade_cal':
                    days=pd.date_range('20250101','20261231').strftime('%Y%m%d')
                    table=pd.DataFrame(dict(exchange='SSE',cal_date=days,is_open=[int(d==DATE) for d in days]))
                    return table[table.is_open==params['is_open']].reset_index(drop=True)
                raise ValueError('数据未齐')
        with tempfile.TemporaryDirectory() as tmp,patch('engine.update.ProMax',return_value=Fake()),patch('engine.update.read_dataset',side_effect=lambda r,o,k:local[k]),patch('engine.update.datetime') as clock:
            clock.now.return_value=NOW
            result=update(Path(tmp)/'source',Path(tmp)/'overlay',through=DATE,force_latest=True)
            self.assertIsNone(result['close_attestation'])
            self.assertEqual(result['updated_days'],0)
            self.assertEqual(result['validation'],'partial')
