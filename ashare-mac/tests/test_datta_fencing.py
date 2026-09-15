import os
import tempfile
import threading
import time
import unittest
import uuid
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from engine.datta import DattaUnavailable
from engine.datta_session import require_session
from mobile_server.artifacts import atomic_json
from mobile_server.datta_ownership import DattaLeaseStore
from mobile_server.queue import JobQueue
from mobile_server.realtime import RealtimeStore


ZONE = ZoneInfo('Asia/Shanghai')


def identity():
    return str(uuid.uuid4())


def active_batch(now):
    return {
        'id': identity(),
        'request_id': identity(),
        'action': 'refresh',
        'status': 'running',
        'created_at': now - 10,
        'executor': 'server',
        'lease': 'a' * 64,
        'lease_until': now + 300,
        'message': '服务器任务仍在运行',
    }


def active_realtime(now):
    return {
        'events': [],
        'runs': [],
        'done': [],
        'lease': {
            'executor': 'server',
            'token': 'b' * 64,
            'expires_at': now + 300,
            'job': {
                'id': '20260915-1430',
                'date': '20260915',
                'previous_date': '20260914',
                'kind': 'screen',
                'scheduled_at': now - 10,
            },
        },
    }


class DattaFencingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.now = datetime(2026, 9, 15, 14, 30, tzinfo=ZONE).timestamp()

    def tearDown(self):
        self.temporary.cleanup()

    def server_owner(self):
        store = DattaLeaseStore(self.root, lambda: self.now)
        self.now += 121
        grant = store.poll('server')
        self.assertTrue(store.activate('server', grant['token']))
        return store, grant

    def test_expired_server_session_does_not_handoff_while_either_server_task_is_still_active(self):
        for kind in ['batch', 'realtime']:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as folder:
                self.root = Path(folder)
                store, server = self.server_owner()
                if kind == 'batch':
                    atomic_json(self.root / 'jobs/status.json', active_batch(self.now))
                else:
                    path = self.root / 'jobs/realtime/state.json'
                    atomic_json(path, active_realtime(self.now))

                self.now += 91
                waiting = store.poll('mac')

                self.assertEqual(waiting, {'owner': 'server', 'phase': 'waiting'})
                self.assertFalse(store.allowed('mac'))
                self.assertEqual(store.public()['epoch'], server['epoch'])

    def test_batch_and_realtime_claims_are_bound_to_the_active_datta_epoch(self):
        store = DattaLeaseStore(self.root, lambda: self.now)
        grant = store.poll('mac')
        self.assertTrue(store.activate('mac', grant['token']))

        queue = JobQueue(self.root / 'jobs', lambda: self.now)
        queue.submit('recompute', identity())
        batch = queue.claim('mac')

        realtime = RealtimeStore(self.root, lambda: self.now)
        realtime.calendar(['20260914', '20260915'])
        screen = realtime.claim('mac')

        self.assertEqual(batch['datta_epoch'], grant['epoch'])
        self.assertEqual(screen['datta_epoch'], grant['epoch'])
        self.assertEqual(queue.state()['datta_epoch'], grant['epoch'])
        self.assertEqual(realtime.state()['lease']['datta_epoch'], grant['epoch'])

    def test_old_epoch_task_cannot_upload_after_same_node_reacquires_the_session(self):
        store = DattaLeaseStore(self.root, lambda: self.now)
        first = store.poll('mac')
        self.assertTrue(store.activate('mac', first['token']))
        queue = JobQueue(self.root / 'jobs', lambda: self.now)
        queue.submit('refresh', identity())
        job = queue.claim('mac')
        self.assertEqual(job['datta_epoch'], first['epoch'])

        self.assertTrue(store.release('mac', first['token']))
        second = store.poll('mac')
        self.assertGreater(second['epoch'], first['epoch'])
        self.assertTrue(store.activate('mac', second['token']))

        self.assertFalse(queue.uploaded(job['id'], job['lease'], 'c' * 64, 10))
        self.assertEqual(queue.state()['status'], 'running')

    def test_unified_source_owner_overrides_legacy_queue_heartbeats(self):
        store,grant=self.server_owner()
        queue=JobQueue(self.root/'jobs',lambda:self.now)
        queue.heartbeat()  # Compute process alive, but source supervisor lost.
        queue.submit('refresh',identity())
        self.assertEqual(queue.claim('server')['datta_epoch'],grant['epoch'])
        realtime=RealtimeStore(self.root,lambda:self.now)
        realtime.calendar(['20260914','20260915']);realtime.pulse('mac')
        self.assertEqual(realtime.claim('server')['datta_epoch'],grant['epoch'])

    def test_local_receipt_epoch_must_match_the_task_epoch(self):
        receipt = self.root / 'datta-session.json'
        monotonic = time.clock_gettime(time.CLOCK_MONOTONIC)
        atomic_json(receipt, {
            'phase': 'active',
            'clock': 'system_monotonic_v1',
            'node': 'mac',
            'epoch': 2,
            'pid': os.getpid(),
            'boot_epoch': time.time() - monotonic,
            'valid_until_monotonic': monotonic + 45,
        })
        with patch.dict(os.environ, {
            'GUANLAN_DATTA_SESSION': str(receipt),
            'GUANLAN_DATTA_EPOCH': '1',
        }):
            with self.assertRaises(DattaUnavailable):
                require_session()
        with patch.dict(os.environ, {
            'GUANLAN_DATTA_SESSION': str(receipt),
            'GUANLAN_DATTA_EPOCH': '2',
        }):
            self.assertEqual(require_session()['epoch'], 2)

    def test_epoch_cannot_rotate_between_validation_and_batch_or_realtime_mutation(self):
        for kind in ['batch', 'realtime']:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                now = [self.now]
                store = DattaLeaseStore(root, lambda: now[0])
                first = store.poll('mac')
                self.assertTrue(store.activate('mac', first['token']))

                if kind == 'batch':
                    queue = JobQueue(root / 'jobs', lambda: now[0])
                    queue.submit('recompute', identity())
                    job = queue.claim('mac')
                    mutate = lambda: queue.progress(job['id'], job['lease'], 'still fenced')
                else:
                    queue = RealtimeStore(root, lambda: now[0])
                    queue.calendar(['20260914', '20260915'])
                    job = queue.claim('mac')
                    mutate = lambda: queue.renew(job['lease'])

                validated = threading.Barrier(2)
                resume = threading.Barrier(2)
                mutation_result = []
                rotation_result = []
                rotation_done = threading.Event()

                def pause_after_epoch_check(*args, **kwargs):
                    validated.wait(timeout=2)
                    resume.wait(timeout=2)
                    return True

                def rotate():
                    released = store.release('mac', first['token'])
                    second = store.poll('mac')
                    activated = store.activate('mac', second['token'])
                    rotation_result.append((released, second['epoch'], activated))
                    rotation_done.set()

                with patch('mobile_server.datta_ownership.epoch_valid', side_effect=pause_after_epoch_check):
                    mutation = threading.Thread(target=lambda: mutation_result.append(mutate()))
                    mutation.start()
                    validated.wait(timeout=2)
                    rotation = threading.Thread(target=rotate)
                    rotation.start()
                    self.assertFalse(rotation_done.wait(0.05), 'epoch rotated while a task mutation was in its critical section')
                    resume.wait(timeout=2)
                    mutation.join(timeout=2)
                    rotation.join(timeout=2)

                self.assertEqual(mutation_result, [True])
                self.assertEqual(rotation_result, [(True, first['epoch'] + 1, True)])



class CrossProcessReceiptTests(unittest.TestCase):
    def test_receipt_is_readable_by_a_separate_python_process(self):
        import subprocess
        import sys
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'session.json';now=time.clock_gettime(time.CLOCK_MONOTONIC)
            atomic_json(p,dict(phase='active',clock='system_monotonic_v1',node='mac',epoch=1,pid=os.getpid(),
                boot_epoch=time.time()-now,valid_until_monotonic=now+45))
            env=dict(os.environ,GUANLAN_DATTA_SESSION=str(p),GUANLAN_DATTA_EPOCH='1')
            result=subprocess.run([sys.executable,'-c','from engine.datta_session import require_session;require_session()'],env=env,capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr.decode())


if __name__ == '__main__':
    unittest.main()
