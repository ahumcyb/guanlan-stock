import json
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch
from mobile_server.mac_worker import run_job


class WorkerRecoveryTests(unittest.TestCase):
    def test_failed_computation_preserves_workspace_without_saving_lease_token(self):
        class Client:
            def request(self,*a,**k):return {'accepted':True}
        job={'id':str(uuid.uuid4()),'lease':'a'*64,'action':'refresh','datta_epoch':3,
             'purpose':'daily_review','expected_as_of':'20260915'}
        with tempfile.TemporaryDirectory() as folder,patch('mobile_server.mac_worker.subprocess.Popen',side_effect=OSError()):
            root=Path(folder)
            with self.assertRaises(OSError):run_job(Client(),{'workspace':str(root),'ssh_config':'unused'},job)
            markers=list(root.glob('*/.failed-job.json'))
            self.assertEqual(len(markers),1)
            value=json.loads(markers[0].read_text())
            self.assertEqual(value['job_id'],job['id'])
            self.assertNotIn(job['lease'],markers[0].read_text())

    def test_upload_checkpoint_survives_workspace_removal_and_has_no_lease(self):
        from mobile_server.mac_worker import checkpoint_bundle
        from engine.snapshot_protocol import sha256_file
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'bundle.zip';source.write_bytes(b'private research artifact')
            job={'id':str(uuid.uuid4()),'lease':'a'*64,'action':'refresh','datta_epoch':3}
            saved=checkpoint_bundle(source,root/'checkpoints',job);source.unlink()
            self.assertEqual(saved.read_bytes(),b'private research artifact')
            self.assertNotIn(job['lease'],saved.name)
            metadata=json.loads(saved.with_suffix('.json').read_text())
            self.assertEqual(metadata['sha256'],sha256_file(saved))
            self.assertNotIn('lease',metadata)
