import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from unittest.mock import patch
import pandas as pd
from engine.close_proof import make_attestation, verify_attestation, verify_package_close
from engine.data import FIELDS


DATE='20260904'
NOW=datetime(2026,9,4,16,11,tzinfo=ZoneInfo('Asia/Shanghai'))


def frames(n=4001):
    keys=pd.DataFrame(dict(ts_code=[f'{i:06d}.SZ' for i in range(n)],trade_date=DATE))
    return {'daily':keys.assign(open=10.,high=11.,low=9.,close=10.,pre_close=10.,vol=100.,amount=100000.),
            'adj_factor':keys.assign(adj_factor=1.),'stk_limit':keys.assign(up_limit=11.,down_limit=9.)}


class CloseProofTests(unittest.TestCase):
    def test_content_changes_and_early_claims_invalidate_attestation(self):
        data=frames();proof=make_attestation(DATE,data,NOW)
        verify_attestation(proof,DATE,data,NOW)
        data['daily'].loc[0,'close']=10.1
        with self.assertRaises(ValueError):verify_attestation(proof,DATE,data,NOW)
        with self.assertRaises(ValueError):make_attestation(DATE,frames(),NOW.replace(hour=14))

    def test_row_order_and_numeric_storage_dtypes_do_not_change_proof(self):
        data=frames();proof=make_attestation(DATE,data,NOW)
        shuffled={k:v.iloc[::-1].reset_index(drop=True) for k,v in data.items()}
        shuffled['daily']['vol']=shuffled['daily'].vol.astype('int64')
        verify_attestation(proof,DATE,shuffled,NOW)

    def test_package_must_match_exact_target_date_and_three_table_proof(self):
        import json
        data=frames();proof=make_attestation(DATE,data,NOW)
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'raw').mkdir()
            (root/'manifest.json').write_text(json.dumps({'as_of':DATE}))
            for kind,frame in data.items():frame.to_parquet(root/'raw'/(kind+'.parquet'),index=False)
            verify_package_close(root,DATE,proof,NOW)
            with self.assertRaises(ValueError):verify_package_close(root,'20260903',proof,NOW)
            wrong=data['adj_factor'].copy();wrong.loc[0,'adj_factor']=2.
            wrong.to_parquet(root/'raw/adj_factor.parquet',index=False)
            with self.assertRaises(ValueError):verify_package_close(root,DATE,proof,NOW)

    def test_future_or_incomplete_proofs_are_not_final_data(self):
        data=frames();proof=make_attestation(DATE,data,NOW)
        with self.assertRaises(ValueError):verify_attestation(proof,DATE,data,NOW.replace(hour=15))
        proof['tables'].pop('stk_limit')
        with self.assertRaises(ValueError):verify_attestation(proof,DATE,data,NOW)

    def test_new_snapshot_replaces_only_attested_day_without_mutating_intraday_source(self):
        import hashlib,json
        from engine.package_data import package
        from engine.data import publish_day
        class Frozen(datetime):
            @classmethod
            def now(cls,tz=None):return NOW
        original=frames();closed={k:v.copy() for k,v in original.items()};closed['daily']['close']=10.1
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'source';raw=root/'raw';raw.mkdir(parents=True)
            for kind,frame in original.items():frame.to_parquet(raw/(kind+'.parquet'),index=False)
            original_hash=hashlib.sha256((raw/'daily.parquet').read_bytes()).hexdigest()
            original['daily'][['ts_code']].assign(name='测试',industry='行业',list_date='20000101').to_parquet(raw/'stock_basic.parquet',index=False)
            pd.DataFrame({'exchange':['SSE'],'cal_date':[DATE],'is_open':[1]}).to_parquet(raw/'trade_cal.parquet',index=False)
            overlay=Path(folder)/'overlay';generation=DATE+'-'+'a'*12
            publish_day(overlay/'closing'/generation,DATE,closed)
            (overlay/'last_update.json').write_text(json.dumps({'closing_generation':generation,'close_attestation':make_attestation(DATE,closed,NOW)}))
            with patch('engine.close_proof.datetime',Frozen):
                result=package(root,overlay,Path(folder)/'packages',closing_date=DATE)
            packaged=pd.read_parquet(result/'raw/daily.parquet')
            self.assertTrue(packaged.close.eq(10.1).all())
            self.assertEqual(hashlib.sha256((raw/'daily.parquet').read_bytes()).hexdigest(),original_hash)
