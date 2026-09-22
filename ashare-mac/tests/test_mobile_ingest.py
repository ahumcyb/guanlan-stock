import hashlib
import errno
import json
import os
import stat
import tempfile
import unittest
import uuid
import zipfile
from pathlib import Path
from unittest.mock import patch

from engine.snapshot_protocol import FILE_NAMES,revision_for
from mobile_server.artifacts import atomic_json,current_manifest
from mobile_server.ingest import activate,extract
from mobile_server.queue import JobQueue


class IngestTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name).resolve()
        for name in ['work','incoming','market']:(self.root/name).mkdir()
        (self.root/'market/staging').mkdir()
        self.queue=JobQueue(self.root/'jobs',lambda:1000)
        self.queue.submit('recompute',str(uuid.uuid4()));self.job=self.queue.claim('mac')
        self.archive=self.root/'incoming/bundle.zip'

    def tearDown(self):self.tmp.cleanup()

    def bundle(self,generation='20260905T120000-abcdef'):
        entries={f'market/raw/{name}':b'bounded fixture '+name.encode() for name in FILE_NAMES}
        manifest={'schema_version':1,'as_of':'20260904','files':[
            {'name':name,'bytes':len(entries['market/raw/'+name]),'rows':1,
             'sha256':hashlib.sha256(entries['market/raw/'+name]).hexdigest()} for name in FILE_NAMES]}
        manifest['revision']=revision_for(manifest)
        metadata={'schema_version':1,'input_revision':manifest['revision'],'data_revision':manifest['revision'],'generation':generation}
        entries['market/manifest.json']=json.dumps(manifest).encode()
        entries['bundle.json']=json.dumps(metadata).encode()
        for strategy in ['leaders','pullback','golden_pit','left_rebound','orderflow']:
            stock={'ts_code':'000001.SZ','name':'测试','industry':'银行',
                'trade_date':'20260904','close':10.0,'change':0.0,'score':1.0,'state':'入选','rank':1,
                'eligible':True,'stale':False,'adjusted':True,'limit_available':True,
                'trend_ok':True,'strength_ok':True,'pullback_ok':True,'volume_ok':True,'turn_ok':True}
            report=json.dumps({'schema_version':1,'strategy_id':strategy,'as_of':'20260904',
                'data_revision':manifest['revision'],'stocks':[stock]}).encode()
            entries[f'research/{strategy}/details/000001.SZ.json']=json.dumps(stock).encode()
            entries[f'research/{strategy}/report.json']=report
            entries[f'research/{strategy}/manifest.json']=json.dumps({'schema_version':1,'strategy':strategy,
                'generation':metadata['generation'],'as_of':'20260904','data_revision':manifest['revision'],
                'report_bytes':len(report),'report_sha256':hashlib.sha256(report).hexdigest(),'stock_count':1}).encode()
        entries['research/charts/000001.SZ.json']=b'[{"date":"20260904"}]'
        with zipfile.ZipFile(self.archive,'w') as output:
            for name,data in entries.items():output.writestr(name,data)
        return metadata

    def ready(self):
        self.bundle();data=self.archive.read_bytes()
        self.queue.uploaded(self.job['id'],self.job['lease'],hashlib.sha256(data).hexdigest(),len(data))

    def test_complete_bundle_is_validated_and_corrupt_research_is_rejected(self):
        metadata=self.bundle();destination=self.root/'extracted';destination.mkdir()
        self.assertEqual(extract(self.archive,destination),metadata)
        with zipfile.ZipFile(self.archive,'a') as output:output.writestr('research/charts/999999.SH.json','[]')
        rejected=self.root/'rejected';rejected.mkdir()
        with self.assertRaises(ValueError):extract(self.archive,rejected)

    def test_missing_detail_is_rejected_before_activation(self):
        self.bundle()
        with zipfile.ZipFile(self.archive) as original:
            members={n:original.read(n) for n in original.namelist() if n!='research/leaders/details/000001.SZ.json'}
        with zipfile.ZipFile(self.archive,'w') as output:
            for name,data in members.items():output.writestr(name,data)
        destination=self.root/'missing-detail';destination.mkdir()
        with self.assertRaisesRegex(ValueError,'Stock details missing'):
            extract(self.archive,destination)

    def test_missing_fourth_report_cannot_replace_current(self):
        self.bundle()
        with zipfile.ZipFile(self.archive) as original:
            members={n:original.read(n) for n in original.namelist() if not n.startswith('research/left_rebound/')}
        with zipfile.ZipFile(self.archive,'w') as output:
            for name,data in members.items():output.writestr(name,data)
        data=self.archive.read_bytes()
        self.queue.uploaded(self.job['id'],self.job['lease'],hashlib.sha256(data).hexdigest(),len(data))
        previous=self.root/'current';previous.mkdir();(previous/'keep').write_text('previous generation')
        with patch('mobile_server.ingest.publish_market') as publisher:
            with self.assertRaises(ValueError):activate(self.archive,self.root,self.root/'market',self.queue,self.job)
            publisher.assert_not_called()
        self.assertEqual((previous/'keep').read_text(),'previous generation')

    def test_closing_job_rejects_an_ordinary_bundle_even_on_the_same_date(self):
        self.queue.failed(self.job['id'],self.job['lease'])
        self.queue.clock=lambda:1400
        self.queue.submit('refresh',str(uuid.uuid4()),expected_as_of='20260904')
        self.job=self.queue.claim('mac');self.ready()
        with patch('mobile_server.ingest.publish_market') as publisher:
            with self.assertRaisesRegex(ValueError,'Closing job target'):
                activate(self.archive,self.root,self.root/'market',self.queue,self.job)
            publisher.assert_not_called()

    def test_archive_rejects_traversal_duplicates_and_symlinks(self):
        for kind in ['traversal','duplicate','symlink']:
            with self.subTest(kind=kind):
                with zipfile.ZipFile(self.archive,'w') as output:
                    if kind=='traversal':output.writestr('../escaped','unsafe')
                    elif kind=='duplicate':
                        import warnings
                        with warnings.catch_warnings():
                            warnings.simplefilter('ignore');output.writestr('bundle.json','{}');output.writestr('bundle.json','{}')
                    else:
                        member=zipfile.ZipInfo('bundle.json');member.external_attr=(stat.S_IFLNK|0o777)<<16
                        output.writestr(member,'/etc/passwd')
                destination=self.root/kind;destination.mkdir()
                with self.assertRaises(ValueError):extract(self.archive,destination)
                self.assertFalse((self.root/'escaped').exists())

    def test_upload_corruption_cannot_reach_market_publication(self):
        self.ready();data=bytearray(self.archive.read_bytes());data[-1]^=1;self.archive.write_bytes(data)
        with patch('mobile_server.ingest.publish_market') as publisher:
            with self.assertRaisesRegex(ValueError,'checksum'):activate(self.archive,self.root,self.root/'market',self.queue,self.job)
            publisher.assert_not_called()
        self.assertEqual(list((self.root/'work').iterdir()),[])

    def test_changed_fingerprint_during_validation_cannot_publish(self):
        self.ready()
        def mutate(bundle,destination):
            result=extract(bundle,destination)
            with self.queue.locked():
                state=self.queue.state();state['artifact_sha256']='b'*64;self.queue.save(state)
            return result
        with patch('mobile_server.ingest.extract',side_effect=mutate),patch('mobile_server.ingest.publish_market') as publisher:
            with self.assertRaisesRegex(ValueError,'identity changed'):activate(self.archive,self.root,self.root/'market',self.queue,self.job)
            publisher.assert_not_called()
        self.assertFalse((self.root/'current').exists())
        self.assertEqual(list((self.root/'work').iterdir()),[])

    def test_api_cannot_change_the_publisher_private_copy(self):
        self.ready();expected=self.archive.read_bytes()
        def replace_original(bundle,destination):
            self.assertEqual(bundle.parent.stat().st_mode&0o777,0o700)
            self.archive.write_bytes(b'late untrusted replacement')
            self.assertEqual(bundle.read_bytes(),expected)
            raise ValueError('stop before activation')
        with patch('mobile_server.ingest.extract',side_effect=replace_original):
            with self.assertRaisesRegex(ValueError,'stop before'):activate(self.archive,self.root,self.root/'market',self.queue,self.job)

    def test_separate_market_mount_can_publish_without_cross_mount_rename(self):
        self.ready();market=self.root/'market';(market/'current').mkdir()
        with zipfile.ZipFile(self.archive) as archive:metadata=json.loads(archive.read('bundle.json'))
        atomic_json(market/'current/manifest.json',{'revision':metadata['input_revision']})
        rename=os.rename
        def mount_rename(source,destination):
            if Path(source).is_relative_to(market)!=Path(destination).is_relative_to(market):
                raise OSError(errno.EXDEV,'Cross-device link')
            return rename(source,destination)
        def publish_market(root,revision):
            from deployment.publish import verify
            verify(root/'staging'/revision,revision)
        with patch('mobile_server.ingest.os.rename',side_effect=mount_rename),patch('mobile_server.ingest.publish_market',side_effect=publish_market):
            activate(self.archive,self.root,market,self.queue,self.job)
        self.assertEqual(self.queue.public()['status'],'completed')
        self.assertEqual((self.root/'current').resolve().name,metadata['generation'])
        self.assertEqual(list((market/'staging').iterdir()),[])

    def test_activation_retention_keeps_latest_historical_momentum_after_four_left_releases(self):
        generation='20260904T161100-abcdef';release=self.root/'releases'/generation
        (release/'momentum_60').mkdir(parents=True);(release/'charts').mkdir()
        report=b'{"strategy_id":"momentum_60","historical":true}'
        (release/'momentum_60/report.json').write_bytes(report)
        atomic_json(release/'momentum_60/manifest.json',{'schema_version':1,'generation':generation,
            'strategy':'momentum_60','as_of':'20260904','data_revision':'20260904-aaaaaaaaaaaaaaaa',
            'report_bytes':len(report),'report_sha256':hashlib.sha256(report).hexdigest(),'stock_count':1})
        chart=b'[{"date":"20260904","close":10}]';(release/'charts/000001.SZ.json').write_bytes(chart)
        os.utime(release,(0,0))

        def publish_market(root,revision):
            from deployment.publish import verify
            verify(root/'staging'/revision,revision)

        self.bundle('20260905T161100-aaaaa1')
        with zipfile.ZipFile(self.archive) as archive:metadata=json.loads(archive.read('bundle.json'))
        (self.root/'market/current').mkdir();atomic_json(self.root/'market/current/manifest.json',{'revision':metadata['input_revision']})
        clock=1000
        with patch('mobile_server.ingest.publish_market',side_effect=publish_market):
            for index in range(4):
                if index:
                    clock+=61;self.queue.clock=lambda value=clock:value
                    self.queue.submit('recompute',str(uuid.uuid4()));self.job=self.queue.claim('mac')
                    self.bundle(f'2026090{5+index}T161100-aaaaa{index+1}')
                data=self.archive.read_bytes()
                self.queue.uploaded(self.job['id'],self.job['lease'],hashlib.sha256(data).hexdigest(),len(data))
                activate(self.archive,self.root,self.root/'market',self.queue,self.job)

        manifest=current_manifest(self.root,'momentum_60')
        self.assertEqual(manifest['generation'],generation)
        self.assertEqual((release/'momentum_60/report.json').read_bytes(),report)
        self.assertEqual((release/'charts/000001.SZ.json').read_bytes(),chart)
