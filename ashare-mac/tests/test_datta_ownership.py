import json
import tempfile
import unittest
import uuid
from pathlib import Path

from mobile_server.artifacts import atomic_json
from mobile_server.datta_ownership import DattaLeaseStore


def identifier():
    return str(uuid.uuid4())


def batch_state(now, status='running'):
    return {
        'id': identifier(),
        'request_id': identifier(),
        'action': 'refresh',
        'status': status,
        'created_at': now - 10,
        'executor': 'server',
        'lease': 'a' * 64,
        'lease_until': now + (1800 if status == 'publishing' else 90),
        'message': '服务器任务执行中',
    }


def realtime_state(now):
    return {
        'events': [],
        'runs': [],
        'done': [],
        'lease': {
            'executor': 'server',
            'token': 'b' * 64,
            'expires_at': now + 90,
            'job': {
                'id': '20260915-1430',
                'date': '20260915',
                'previous_date': '20260914',
                'kind': 'screen',
                'scheduled_at': now - 10,
            },
        },
    }


class DattaOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.now = 1_800_000_000.0
        self.store = DattaLeaseStore(self.root, lambda: self.now)

    def tearDown(self):
        self.temporary.cleanup()

    def assert_grant(self, value, owner, phase='reserved'):
        self.assertEqual(value['owner'], owner)
        self.assertEqual(value['phase'], phase)
        self.assertIsInstance(value['epoch'], int)
        self.assertGreater(value['epoch'], 0)
        self.assertRegex(value['token'], r'^[a-f0-9]{64}$')
        self.assertAlmostEqual(value['lease_until'], self.now + 90)

    def test_startup_grace_is_persisted_and_mac_poll_has_priority(self):
        waiting = self.store.poll('server')
        self.assertEqual(waiting['phase'], 'waiting')
        self.assertNotIn('token', waiting)

        self.now += 119
        restarted = DattaLeaseStore(self.root, lambda: self.now)
        self.assertEqual(restarted.poll('server')['phase'], 'waiting')

        mac = restarted.poll('mac')
        self.assert_grant(mac, 'mac')
        self.assertFalse(restarted.allowed('server'))
        self.assertFalse(restarted.allowed('mac'))
        self.assertTrue(restarted.activate('mac', mac['token']))
        self.assertTrue(restarted.allowed('mac'))

        before = mac['lease_until']
        self.now += 30
        renewed = restarted.poll('mac', mac['token'])
        self.assertEqual(renewed['token'], mac['token'])
        self.assertEqual(renewed['epoch'], mac['epoch'])
        self.assertEqual(renewed['phase'], 'active')
        self.assertGreater(renewed['lease_until'], before)

    def test_server_can_acquire_only_after_the_full_initial_mac_grace(self):
        self.assertEqual(self.store.poll('server')['phase'], 'waiting')
        self.now += 119
        self.assertEqual(self.store.poll('server')['phase'], 'waiting')
        self.now += 2
        server = self.store.poll('server')
        self.assert_grant(server, 'server')

    def test_expired_token_cannot_renew_release_or_clear_a_new_epoch(self):
        first = self.store.poll('mac')
        self.assertTrue(self.store.activate('mac', first['token']))
        self.now += 91

        stale = self.store.poll('mac', first['token'])
        self.assertNotEqual(stale.get('token'), first['token'])
        self.assertFalse(self.store.release('mac', first['token']))

        second = stale if stale.get('token') else self.store.poll('mac')
        self.assert_grant(second, 'mac')
        self.assertGreater(second['epoch'], first['epoch'])
        self.assertFalse(self.store.release('mac', first['token']))
        self.assertEqual(self.store.public()['epoch'], second['epoch'])

    def test_mac_recovery_waits_for_an_active_server_batch_then_drains_before_handoff(self):
        self.now += 121
        server = self.store.poll('server')
        self.assertTrue(self.store.activate('server', server['token']))
        jobs = self.root / 'jobs'
        jobs.mkdir(exist_ok=True)
        atomic_json(jobs / 'status.json', batch_state(self.now, 'publishing'))

        mac_waiting = self.store.poll('mac')
        self.assertEqual(mac_waiting, {'owner': 'server', 'phase': 'waiting'})
        self.assertTrue(self.store.allowed('server'))

        self.now += 15
        continued = self.store.poll('server', server['token'])
        self.assertEqual(continued['phase'], 'active')
        self.assertTrue(self.store.allowed('server'))

        finished = batch_state(self.now, 'completed')
        finished.pop('lease')
        finished.pop('lease_until')
        atomic_json(jobs / 'status.json', finished)
        draining = self.store.poll('server', server['token'])
        self.assertEqual(draining['phase'], 'draining')
        self.assertFalse(self.store.allowed('server'))
        self.assertEqual(self.store.poll('mac'), {'owner': 'server', 'phase': 'waiting'})

        self.assertTrue(self.store.release('server', server['token']))
        mac = self.store.poll('mac')
        self.assert_grant(mac, 'mac')
        self.assertEqual(mac['epoch'], server['epoch'] + 1)

    def test_realtime_server_lease_also_blocks_handoff_until_it_finishes(self):
        self.now += 121
        server = self.store.poll('server')
        self.assertTrue(self.store.activate('server', server['token']))
        folder = self.root / 'jobs' / 'realtime'
        folder.mkdir(parents=True)
        atomic_json(folder / 'state.json', realtime_state(self.now))

        self.assertEqual(self.store.poll('mac')['phase'], 'waiting')
        self.now += 15
        self.assertEqual(self.store.poll('server', server['token'])['phase'], 'active')

        atomic_json(folder / 'state.json', {'events': [], 'runs': [], 'done': []})
        self.assertEqual(self.store.poll('server', server['token'])['phase'], 'draining')
        self.assertFalse(self.store.allowed('server'))

    def test_restart_preserves_active_owner_and_public_state_never_contains_token(self):
        mac = self.store.poll('mac')
        self.assertTrue(self.store.activate('mac', mac['token']))
        restarted = DattaLeaseStore(self.root, lambda: self.now)

        self.assertTrue(restarted.allowed('mac'))
        self.assertFalse(restarted.allowed('server'))
        public = restarted.public()
        self.assertEqual(public['owner'], 'mac')
        self.assertEqual(public['phase'], 'active')
        self.assertEqual(public['epoch'], mac['epoch'])
        self.assertNotIn('token', json.dumps(public))

    def test_invalid_node_or_token_cannot_change_owner(self):
        with self.assertRaises(ValueError):
            self.store.poll('other')
        mac = self.store.poll('mac')
        self.assertFalse(self.store.activate('server', mac['token']))
        self.assertFalse(self.store.activate('mac', 'bad'))
        self.assertFalse(self.store.release('mac', 'bad'))
        self.assertEqual(self.store.public()['owner'], 'mac')

    def test_unconfirmed_client_shutdown_renews_ownership_without_allowing_new_jobs(self):
        grant=self.store.poll('mac');self.store.activate('mac',grant['token'])
        for _ in range(6):
            self.now+=30
            self.assertTrue(self.store.deactivate('mac',grant['token']))
            self.assertFalse(self.store.allowed('mac'))
            self.assertEqual(self.store.poll('server'),{'owner':'mac','phase':'waiting'})
            self.assertEqual(self.store.public()['epoch'],grant['epoch'])



if __name__ == '__main__':
    unittest.main()
