import json
import tempfile
import unittest
from pathlib import Path
from engine.intraday import local_now
from mobile_server.api import Service, Failure
from mobile_server.realtime import RealtimeStore, bark_key


class RealtimeTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory();self.root = Path(self.folder.name)
        self.now = local_now().replace(year=2026, month=9, day=4, hour=14, minute=50, second=0, microsecond=0).timestamp()
        self.store = RealtimeStore(self.root, lambda: self.now)
        self.store.calendar(['20260903', '20260904', '20260907'])

    def tearDown(self):
        self.folder.cleanup()

    def report(self, job):
        return dict(schema_version=1, date=job['date'], previous_date=job['previous_date'], generated_at=self.now,
            kind=job['kind'], strategies={'overnight': [], 'golden': []}, reviews=[], status='ready', message='完成')

    def test_mac_priority_fencing_and_dedup(self):
        self.store.pulse('mac')
        self.assertIsNone(self.store.claim('server'))
        job = self.store.claim('mac');self.assertIsNotNone(job)
        self.now += 91
        server = self.store.claim('server');self.assertIsNotNone(server)
        self.assertFalse(self.store.publish(job['lease'], self.report(job)))
        self.assertTrue(self.store.publish(server['lease'], self.report(server)))
        self.assertIsNone(self.store.claim('mac'))
        self.assertEqual(len(self.store.public()['events']), 1)
        self.assertNotIn('lease', json.dumps(self.store.public()))
        self.assertEqual(RealtimeStore(self.root, lambda: self.now).public()['latest']['executor'], 'server')

    def test_closed_day_and_expired_slot(self):
        self.now += 86400
        self.assertIsNone(self.store.claim('mac'))
        self.now -= 86400 - 180
        self.assertIsNone(self.store.claim('mac'))

    def test_notification_secret_and_ambiguous_delivery(self):
        key = 'safeTestingKeyForOwnDevice123'
        self.store.configure({'bark_url': 'https://api.day.app/' + key, 'deepseek_key': 'safeTestDeepSeekKey123'})
        self.assertNotIn(key, json.dumps(self.store.public()))
        self.assertNotIn('safeTestDeepSeekKey123', json.dumps(self.store.public()))
        self.store.test_notification();event, actual = self.store.take_event()
        self.assertEqual(actual, key)
        self.store.finish_event(event['id'], 'unknown')
        self.now += 40
        self.assertIsNone(self.store.take_event())
        self.assertEqual(self.store.public()['events'][0]['status'], 'unknown')
        self.store.configure({'clear_bark': True, 'clear_deepseek': True})
        self.assertFalse(self.store.public_settings()['deepseek_configured'])

    def test_host_redirect_injection_and_setting_types(self):
        self.assertEqual(bark_key('https://api.day.app/testingDeviceKey12345/这里是测试内容'),'testingDeviceKey12345')
        for value in ['http://api.day.app/' + 'a'*20, 'https://api.day.app.evil.test/' + 'a'*20,
                      'https://api.day.app@evil.test/' + 'a'*20, 'https://api.day.app/' + 'a'*20+'?x=1']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                bark_key(value)
        for settings in [{'enabled': 'true'}, {'model': 'unknown'}, {'endpoint': 'http://localhost'}]:
            with self.assertRaises(ValueError):
                self.store.configure(settings)

    def test_rejected_date_and_tampered_result(self):
        job = self.store.claim('mac');report = self.report(job)
        report['previous_date'] = '20260902'
        with self.assertRaises(ValueError):
            self.store.publish(job['lease'], report)
        report = self.report(job);report['generated_at'] = self.now + 60
        with self.assertRaises(ValueError):
            self.store.publish(job['lease'], report)
        self.assertEqual(len(self.store.public()['events']), 0)

    def test_api_auth_and_settings_never_return_credentials(self):
        service = Service(self.root, 'a'*64, 'b'*64)
        with self.assertRaises(Failure) as error:
            service.dispatch('GET', '/v1/realtime', '')
        self.assertEqual(error.exception.status, 401)
        with self.assertRaises(Failure):
            service.dispatch('POST', '/v1/worker/realtime/claim', 'Bearer '+ 'a'*64, b'{}')
        for action in ['settings','test','scan']:
            with self.subTest(action=action), self.assertRaises(Failure):
                service.dispatch('POST', '/v1/worker/realtime/'+action, 'Bearer '+'b'*64, b'{}')
        code, value = service.dispatch('POST', '/v1/realtime/settings', 'Bearer '+ 'a'*64,
                    json.dumps({'bark_url': 'https://api.day.app/safeDeviceTestingKey12345'}).encode())
        self.assertEqual(code, 200);self.assertTrue(value['bark_configured'])
        self.assertNotIn('safeDeviceTestingKey12345', json.dumps(value))

    def test_pausing_automatic_jobs_still_allows_manual_check(self):
        self.store.configure({'enabled': False})
        self.assertIsNone(self.store.claim('mac'))
        self.store.request_scan()
        job=self.store.claim('mac')
        self.assertTrue(job['id'].startswith('manual-'))


if __name__ == '__main__':
    unittest.main()
