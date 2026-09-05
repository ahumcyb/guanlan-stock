import io
import json
import tempfile
import unittest
import uuid
from pathlib import Path
from mobile_server.queue import JobQueue
from mobile_server.api import Service,Failure


class LeaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name).resolve();self.now=1000
        self.queue=JobQueue(self.root/'jobs',lambda:self.now)
        self.job=self.queue.submit('recompute',str(uuid.uuid4()))
    def tearDown(self):self.tmp.cleanup()

    def test_mac_is_preferred_and_only_one_executor_claims(self):
        self.queue.heartbeat()
        self.assertIsNone(self.queue.claim('server'))
        mac=self.queue.claim('mac');self.assertEqual(mac['executor'],'mac')
        self.assertIsNone(self.queue.claim('mac'));self.assertIsNone(self.queue.claim('server'))
        self.assertNotIn('lease',self.queue.public())

    def test_server_takes_over_when_mac_lease_expires_and_late_upload_is_rejected(self):
        self.queue.heartbeat();mac=self.queue.claim('mac')
        self.now+=91
        server=self.queue.claim('server')
        self.assertEqual(server['id'],mac['id']);self.assertNotEqual(server['lease'],mac['lease'])
        self.assertFalse(self.queue.uploaded(mac['id'],mac['lease'],'b'*64,20))
        self.assertFalse(self.queue.progress(mac['id'],mac['lease'],'late'))
        self.assertEqual(self.queue.state()['executor'],'server')

    def test_renewing_mac_lease_prevents_server_takeover(self):
        self.queue.heartbeat();mac=self.queue.claim('mac')
        for _ in range(8):
            self.now+=20;self.assertTrue(self.queue.heartbeat(mac['id'],mac['lease']))
            self.assertIsNone(self.queue.claim('server'))

    def test_phone_credential_cannot_claim_or_upload(self):
        service=Service(self.root,'a'*64,'b'*64);service.queue=self.queue
        with self.assertRaises(Failure) as error:service.dispatch('POST','/v1/worker/claim','Bearer '+'a'*64,b'{}')
        self.assertEqual(error.exception.status,401)
        with self.assertRaises(Failure):service.upload('/v1/worker/uploads/'+self.job['id'],'Bearer '+'a'*64,'c'*64,io.BytesIO(b'xx'),2)

    def test_incomplete_or_expired_upload_cannot_be_published(self):
        service=Service(self.root,'a'*64,'b'*64);service.queue=self.queue
        mac=self.queue.claim('mac');path='/v1/worker/uploads/'+mac['id']
        with self.assertRaises(Failure):service.upload(path,'Bearer '+'b'*64,mac['lease'],io.BytesIO(b'x'),2)
        self.assertEqual(list((self.root/'incoming').iterdir()),[])
        self.now+=91
        with self.assertRaises(Failure) as error:service.upload(path,'Bearer '+'b'*64,mac['lease'],io.BytesIO(b'xx'),2)
        self.assertEqual(error.exception.status,409)

    def test_publishing_cannot_be_reuploaded_cancelled_or_renewed_by_client(self):
        service=Service(self.root,'a'*64,'b'*64);service.queue=self.queue
        mac=self.queue.claim('mac');path='/v1/worker/uploads/'+mac['id']
        service.upload(path,'Bearer '+'b'*64,mac['lease'],io.BytesIO(b'first'),5)
        captured=self.queue.state()
        with self.assertRaises(Failure):service.upload(path,'Bearer '+'b'*64,mac['lease'],io.BytesIO(b'changed'),7)
        self.assertFalse(self.queue.uploaded(mac['id'],mac['lease'],'c'*64,8))
        self.assertFalse(self.queue.failed(mac['id'],mac['lease']))
        self.assertFalse(self.queue.heartbeat(mac['id'],mac['lease']))
        self.assertEqual(self.queue.state(),captured)
        self.assertEqual(next((self.root/'incoming').glob('*.zip')).read_bytes(),b'first')

    def test_slow_publication_has_bounded_server_owned_deadline(self):
        mac=self.queue.claim('mac');self.queue.uploaded(mac['id'],mac['lease'],'b'*64,20)
        self.now+=600
        self.assertTrue(self.queue.owns(self.queue.state(),mac['id'],mac['lease']))
        self.assertIsNone(self.queue.claim('server'))
        self.now+=1201
        server=self.queue.claim('server');self.assertEqual(server['executor'],'server')
