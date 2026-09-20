import copy
import gzip
import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from engine.chart_data import make_extended, validate_extended, read_extended, write_extended, MAX_EXTENDED
from mobile_server.api import Failure
from mobile_server.artifacts import publish, current_manifest
from tests import test_mobile_api as api_fixture
from tests import test_mobile_ingest as ingest_fixture

REVISION='20260904-aaaaaaaaaaaaaaaa'


def group(count=510):
    days=pd.bdate_range(end='2026-09-04',periods=count).strftime('%Y%m%d').tolist()
    return pd.DataFrame(dict(trade_date=days,open=[10.]*count,high=[12.]*count,low=[9.]*count,
        close=[11.]*count,pre_close=[11.]*count,adj_open=[100.]*count,adj_high=[120.]*count,
        adj_low=[90.]*count,price=[110.]*count,ma10=[105.]*count,ma20=[103.]*count,ma60=[100.]*count,
        vol=[12345.]*count,amount=[13579.]*count))


class ExtendedChartTests(unittest.TestCase):
    def test_500_limit_raw_and_continuous_prices_units_and_fixed_revision(self):
        frame=group();frame.loc[frame.index[0],'price']=55.
        value=make_extended(frame,'000001.SZ','20260904',REVISION)
        validate_extended(value,'000001.SZ','20260904',REVISION)
        self.assertEqual(len(value['bars']),500)
        self.assertEqual(value['volume_unit'],'lot')
        self.assertEqual(value['price_basis'],'continuous_latest_close')
        bar=value['bars'][-1]
        self.assertEqual((bar['close'],bar['raw_close'],bar['raw_pre_close']),(11.,11.,11.))
        self.assertEqual(bar['volume'],12345.)
        self.assertEqual(bar['amount'],13579.)

    def test_revision_date_ohlc_moving_average_and_basis_mismatches_are_rejected(self):
        original=make_extended(group(10),'000001.SZ','20260904',REVISION)
        for key,value in [('date','20260907'),('ma10',-1.),('volume',-1.),('raw_close',100.),('high',0.),('raw_pre_close',True)]:
            candidate=copy.deepcopy(original);candidate['bars'][0][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):validate_extended(candidate,'000001.SZ','20260904',REVISION)
        with self.assertRaises(ValueError):validate_extended(original,'000002.SZ','20260904',REVISION)
        with self.assertRaises(ValueError):validate_extended(original,'000001.SZ','20260904','20260904-'+'b'*16)

    def test_compression_limits_duplicate_dates_and_legacy_agreement(self):
        value=make_extended(group(),'000001.SZ','20260904',REVISION)
        legacy=[{k:b[k] for k in ['date','open','high','low','close','ma10','ma20','ma60','volume']} for b in value['bars'][-120:]]
        validate_extended(value,'000001.SZ','20260904',REVISION,legacy)
        wrong=copy.deepcopy(legacy);wrong[-1]['close']=99.
        with self.assertRaises(ValueError):validate_extended(value,'000001.SZ','20260904',REVISION,wrong)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'chart.json.gz';write_extended(path,value)
            self.assertEqual(read_extended(path,'000001.SZ','20260904',REVISION),value)
            path.write_bytes(gzip.compress(b' '*(MAX_EXTENDED+1)))
            with self.assertRaises(ValueError):read_extended(path,'000001.SZ','20260904',REVISION)
        wrong=copy.deepcopy(value);wrong['bars'].append(wrong['bars'][-1])
        with self.assertRaises(ValueError):validate_extended(wrong,'000001.SZ','20260904',REVISION)

    def test_return_chain_latest_anchor_and_padding_are_rejected(self):
        original=make_extended(group(10),'000001.SZ','20260904',REVISION)
        wrong=copy.deepcopy(original);wrong['bars'][-1]['raw_pre_close']=1.
        with self.assertRaises(ValueError):validate_extended(wrong,'000001.SZ','20260904',REVISION)
        wrong=copy.deepcopy(original)
        for bar in wrong['bars']:
            for key in ['open','high','low','close','ma10','ma20','ma60']:bar[key]*=2
        with self.assertRaises(ValueError):validate_extended(wrong,'000001.SZ','20260904',REVISION)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'padded.json.gz';path.write_bytes(gzip.compress(b' '*100+json.dumps(original).encode()))
            with self.assertRaises(ValueError):read_extended(path,'000001.SZ','20260904',REVISION)


class ExtendedChartAPITests(unittest.TestCase):
    setUp=api_fixture.MobileAPITests.setUp
    tearDown=api_fixture.MobileAPITests.tearDown
    outputs=api_fixture.MobileAPITests.outputs
    call=api_fixture.MobileAPITests.call
    def extended_outputs(self):
        outputs=self.outputs();value=make_extended(group(),'000001.SZ','20260904',REVISION)
        legacy=[{k:b[k] for k in ['date','open','high','low','close','ma10','ma20','ma60','volume']} for b in value['bars'][-120:]]
        for strategy in ['leaders','pullback','golden_pit','left_rebound','orderflow']:
            folder=outputs/strategy/'20260905T120000-abcdef'
            (folder/'charts/000001.SZ.json').write_text(json.dumps(legacy))
            write_extended(folder/'charts-extended/000001.SZ.json.gz',value)
        return outputs,value

    def test_new_route_returns_extended_but_old_route_remains_120(self):
        outputs,value=self.extended_outputs();manifests=publish(outputs,self.root,REVISION);generation=manifests['leaders']['generation']
        code,result=self.call('GET',f'/v1/reports/leaders/{generation}/charts-extended/000001.SZ.json')
        self.assertEqual(code,200);self.assertEqual(result,value)
        legacy=self.call('GET',f'/v1/reports/leaders/{generation}/charts/000001.SZ.json')[1]
        self.assertEqual(len(json.loads(legacy.read_text())),120)

    def test_legacy_release_has_an_explicit_missing_extended_response(self):
        manifests=publish(self.outputs(),self.root,REVISION)
        with self.assertRaises(Failure) as error:
            self.call('GET',f'/v1/reports/leaders/{manifests["leaders"]["generation"]}/charts-extended/000001.SZ.json')
        self.assertEqual(error.exception.status,404)

    def test_incomplete_or_conflicting_extended_data_cannot_replace_current(self):
        outputs,_=self.extended_outputs();first=publish(outputs,self.root,REVISION)
        path=outputs/'pullback/20260905T120000-abcdef/charts-extended/000001.SZ.json.gz';path.unlink()
        with self.assertRaises(ValueError):publish(outputs,self.root,REVISION)
        self.assertEqual(current_manifest(self.root,'leaders'),first['leaders'])


class ExtendedChartIngestTests(unittest.TestCase):
    setUp=ingest_fixture.IngestTests.setUp
    tearDown=ingest_fixture.IngestTests.tearDown
    bundle=ingest_fixture.IngestTests.bundle
    def test_extended_files_are_allowlisted_validated_and_complete(self):
        import zipfile
        metadata=self.bundle();value=make_extended(group(10),'000001.SZ','20260904',metadata['data_revision'])
        legacy=[{k:b[k] for k in ['date','open','high','low','close','ma10','ma20','ma60','volume']} for b in value['bars']]
        with zipfile.ZipFile(self.archive) as archive:entries={name:archive.read(name) for name in archive.namelist()}
        entries['research/charts/000001.SZ.json']=json.dumps(legacy).encode()
        entries['research/charts-extended/000001.SZ.json.gz']=gzip.compress(json.dumps(value,separators=(',',':')).encode())
        with zipfile.ZipFile(self.archive,'w') as archive:
            for name,data in entries.items():archive.writestr(name,data)
        from mobile_server.ingest import extract
        destination=self.root/'extended';destination.mkdir();self.assertEqual(extract(self.archive,destination),metadata)
        from unittest.mock import patch
        expanded=sum(len(data) for name,data in entries.items() if not name.endswith('.gz'))+len(gzip.decompress(entries['research/charts-extended/000001.SZ.json.gz']))
        destination=self.root/'budget';destination.mkdir()
        with patch('mobile_server.ingest.MAX_EXPANDED_TOTAL',expanded-1),self.assertRaises(ValueError):extract(self.archive,destination)
        with zipfile.ZipFile(self.archive,'a') as archive:archive.writestr('research/charts-extended/000002.SZ.json.gz',gzip.compress(b'{}'))
        destination=self.root/'invalid';destination.mkdir()
        with self.assertRaises(ValueError):extract(self.archive,destination)
