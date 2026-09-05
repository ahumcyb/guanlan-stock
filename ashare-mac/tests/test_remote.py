import hashlib
import json
import tempfile
import unittest
import sys
import os
from pathlib import Path

from engine.snapshot_protocol import FILE_NAMES, revision_for, validate_manifest,prune_snapshots
from deployment.ssh_gateway import resolve_request
from engine.remote import sync,SshTransport
from deployment.publish import verify


def manifest():
    value={'schema_version':1,'as_of':'20260904','files':[
        {'name':name,'bytes':10,'rows':2,'sha256':'a'*64} for name in FILE_NAMES]}
    value['revision']=revision_for(value)
    return value


class ProtocolTests(unittest.TestCase):
    def test_manifest_content_cannot_be_changed_without_revision(self):
        value=manifest(); value['files'][0]['bytes']=11
        with self.assertRaises(ValueError): validate_manifest(value)

    def test_extra_files_and_path_traversal_are_rejected(self):
        value=manifest();value['files'][0]['name']='../../.ssh/id_rsa'
        value['revision']=revision_for(value)
        with self.assertRaises(ValueError): validate_manifest(value)

    def test_manifest_requires_all_five_datasets(self):
        value=manifest();value['files'].pop();value['revision']=revision_for(value)
        with self.assertRaises(ValueError): validate_manifest(value)

    def test_valid_manifest_is_accepted(self):
        validate_manifest(manifest())


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name)
        self.value=manifest(); self.revision=self.value['revision']
        self.release=self.root/'releases'/self.revision
        (self.release/'raw').mkdir(parents=True)
        (self.release/'manifest.json').write_text(json.dumps(self.value))
        (self.release/'raw'/'daily.parquet').write_bytes(b'public data')
        (self.root/'current').symlink_to(self.release)

    def tearDown(self): self.temp.cleanup()

    def test_only_allowlisted_commands_are_available(self):
        with self.assertRaises(ValueError): resolve_request(self.root,'id')
        with self.assertRaises(ValueError): resolve_request(self.root,'manifest; cat /etc/shadow')

    def test_path_traversal_is_rejected(self):
        with self.assertRaises(ValueError): resolve_request(self.root,f'file {self.revision} ../../etc/shadow')

    def test_reading_manifest_and_allowed_data(self):
        self.assertEqual(resolve_request(self.root,'manifest'),(self.release/'manifest.json').resolve())
        self.assertEqual(resolve_request(self.root,f'file {self.revision} daily.parquet').read_bytes(),b'public data')

    def test_symlink_cannot_escape_release_directory(self):
        outside=self.root/'outside';outside.write_bytes(b'not served')
        (self.release/'raw'/'adj_factor.parquet').symlink_to(outside)
        with self.assertRaises(ValueError): resolve_request(self.root,f'file {self.revision} adj_factor.parquet')

    def test_publisher_rejects_symlinked_manifest_before_root_file_changes(self):
        payload=b'public data'
        for entry in self.value['files']:
            entry.update(bytes=len(payload),sha256=hashlib.sha256(payload).hexdigest())
            (self.release/'raw'/entry['name']).write_bytes(payload)
        self.value['revision']=revision_for(self.value)
        release=self.release.with_name(self.value['revision']);self.release.rename(release)
        self.release=release;self.revision=self.value['revision']
        (release/'manifest.json').write_text(json.dumps(self.value))
        verify(release.resolve(),self.revision)  # A complete valid release first.
        outside=self.root/'external.json';outside.write_text(json.dumps(self.value))
        (self.release/'manifest.json').unlink();(self.release/'manifest.json').symlink_to(outside)
        with self.assertRaises(ValueError):verify(self.release.resolve(),self.revision)


class RetentionTests(unittest.TestCase):
    def test_keep_current_and_two_previous_after_retirement_grace(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);revisions=[]
            for day in range(1,6):
                value=manifest();value['as_of']=f'202609{day:02d}';value['revision']=revision_for(value)
                path=root/value['revision'];path.mkdir();(path/'manifest.json').write_text(json.dumps(value))
                os.utime(path,(day,day));revisions.append(value['revision'])
            # The outgoing current may have been created long ago; it still gets 24h.
            self.assertEqual(prune_snapshots(root,revisions[-1],revisions[-2],now=100),[])
            self.assertEqual(prune_snapshots(root,revisions[-1],now=86499),[])
            removed=prune_snapshots(root,revisions[-1],now=86501)
            self.assertEqual(set(removed),set(revisions[:2]))
            self.assertTrue(all((root/revision).is_dir() for revision in revisions[2:]))

    def test_rollback_resets_retirement_and_unknown_paths_are_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);revisions=[]
            for day in range(1,5):
                value=manifest();value['as_of']=f'202609{day:02d}';value['revision']=revision_for(value)
                path=root/value['revision'];path.mkdir();(path/'manifest.json').write_text(json.dumps(value))
                revisions.append(value['revision'])
            unknown=root/'do-not-delete';unknown.mkdir()
            linked=root/'20260910-aaaaaaaaaaaaaaaa';linked.symlink_to(unknown,target_is_directory=True)
            prune_snapshots(root,revisions[3],now=100)
            prune_snapshots(root,revisions[0],revisions[3],now=200)
            self.assertFalse((root/'.retired'/revisions[0]).exists())
            prune_snapshots(root,revisions[3],revisions[0],now=100000)
            self.assertTrue((root/revisions[0]).exists())
            self.assertTrue(unknown.exists());self.assertTrue(linked.is_symlink())


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.source=self.root/'source';self.source.mkdir()
        import pandas as pd
        files=[]
        for name in FILE_NAMES:
            path=self.source/name;pd.DataFrame({'value':[1]}).to_parquet(path,index=False)
            data=path.read_bytes()
            files.append(dict(name=name,bytes=len(data),rows=1,sha256=hashlib.sha256(data).hexdigest()))
        self.value={'schema_version':1,'as_of':'20260904','files':files}
        self.value['revision']=revision_for(self.value)
        owner=self
        class Fake:
            def __init__(self):self.transfers=0;self.corrupt=False
            def manifest(self):return owner.value
            def file(self,revision,name,destination,expected_bytes):
                self.transfers+=1
                destination.write_bytes(b'corrupt' if self.corrupt else (owner.source/name).read_bytes())
        self.transport=Fake();self.cache=self.root/'cache'

    def tearDown(self):self.tmp.cleanup()

    def test_complete_snapshot_is_activated_and_repeated_sync_reuses_files(self):
        result=sync({},self.cache,self.transport)
        self.assertEqual((self.cache/'current').resolve(),result)
        sync({},self.cache,self.transport)
        self.assertEqual(self.transport.transfers,5)

    def test_corrupt_transfer_cannot_replace_previous_cache(self):
        previous=sync({},self.cache,self.transport)
        self.value['as_of']='20260905';self.value['revision']=revision_for(self.value)
        self.transport.corrupt=True
        with self.assertRaises(ValueError):sync({},self.cache,self.transport)
        self.assertEqual((self.cache/'current').resolve(),previous)

    def test_data_client_does_not_use_root(self):
        with self.assertRaises(ValueError):SshTransport({'host':'106.14.125.189','user':'root'})

    def test_ssh_response_is_aborted_at_declared_size(self):
        transport=object.__new__(SshTransport)
        transport.prefix=[sys.executable,'-c','import sys;sys.stdout.buffer.write(b"x"*1000000)']
        with self.assertRaises(ValueError):transport._run('manifest',limit=128)

    def test_ssh_stderr_cannot_block_or_fill_memory(self):
        transport=object.__new__(SshTransport)
        transport.prefix=[sys.executable,'-c','import sys;sys.stderr.buffer.write(b"x"*1000000);sys.stdout.buffer.write(b"{}")']
        self.assertEqual(transport._run('manifest',limit=128),b'{}')
