import tempfile
import unittest
import uuid
from unittest.mock import patch
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from mobile_server.realtime import RealtimeStore


ZONE = ZoneInfo('Asia/Shanghai')


class RealtimeHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.now = datetime(2026, 9, 4, 14, 30, tzinfo=ZONE).timestamp()
        self.store = RealtimeStore(self.root, lambda: self.now)
        self.store.calendar(['20260903', '20260904', '20260907'])

    def tearDown(self):
        self.temporary.cleanup()

    def report(self, job, message, status='ready', run_state='complete'):
        return {
            'schema_version': 1,
            'date': job['date'],
            'previous_date': job['previous_date'],
            'generated_at': self.now,
            'kind': job['kind'],
            'strategies': {'overnight': [], 'golden': []},
            'reviews': [],
            'status': status,
            'run_state': run_state,
            'message': message,
        }

    def publish_scheduled(self, hour, minute, message):
        self.now = datetime(2026, 9, 4, hour, minute, tzinfo=ZONE).timestamp()
        job = self.store.claim('mac')
        self.assertIsNotNone(job)
        self.assertTrue(self.store.publish(job['lease'], self.report(job, message)))
        return job['id']

    def test_out_of_window_manual_waiting_run_does_not_replace_last_complete_screen(self):
        complete_slot = self.publish_scheduled(14, 30, '完整初筛')

        self.now = datetime(2026, 9, 4, 15, 30, tzinfo=ZONE).timestamp()
        self.store.request_scan()
        manual = self.store.claim('mac')
        self.assertIsNotNone(manual)
        self.assertTrue(manual['id'].startswith('manual-'))
        waiting = self.report(manual, '当前不在策略时段，等待下一轮', status='blocked', run_state='waiting')
        self.assertTrue(self.store.publish(manual['lease'], waiting))

        public = self.store.public()
        self.assertEqual(public['latest']['slot'], manual['id'])
        self.assertEqual(public['latest']['run_state'], 'waiting')
        self.assertEqual(public['last_screen']['slot'], complete_slot)
        self.assertEqual(public['last_screen']['run_state'], 'complete')
        summaries = self.store.history()
        self.assertEqual([row['slot'] for row in summaries[:2]], [manual['id'], complete_slot])
        self.assertEqual(summaries[0]['run_state'], 'waiting')

    def test_old_notification_stays_bound_to_its_original_complete_run_after_later_rounds_and_restart(self):
        first_slot = self.publish_scheduled(14, 30, '第一轮完整筛选')
        first_event = self.store.state()['events'][-1]
        self.assertEqual(first_event['run_id'], first_slot)

        second_slot = self.publish_scheduled(14, 45, '第二轮完整筛选')
        third_slot = self.publish_scheduled(14, 50, '第三轮完整筛选')

        detail = self.store.event_detail(first_event['id'])
        self.assertEqual(detail['event']['id'], first_event['id'])
        self.assertEqual(detail['event']['body'], first_event['body'])
        self.assertEqual(detail['report']['slot'], first_slot)
        self.assertEqual(detail['report']['message'], '第一轮完整筛选')
        self.assertNotEqual(detail['report']['slot'], third_slot)
        self.assertEqual(self.store.run(second_slot)['message'], '第二轮完整筛选')

        restarted = RealtimeStore(self.root, lambda: self.now)
        self.assertEqual(restarted.run(first_slot)['message'], '第一轮完整筛选')
        self.assertEqual(restarted.event_detail(first_event['id'])['report']['slot'], first_slot)
        self.assertEqual([row['slot'] for row in restarted.history()[:3]], [third_slot, second_slot, first_slot])

    def test_legacy_event_without_run_binding_preserves_message_and_never_uses_latest_report(self):
        latest_slot = self.publish_scheduled(14, 30, '当前最新报告')
        state = self.store.state()
        legacy_id = str(uuid.uuid4())
        state['events'].append({
            'id': legacy_id,
            'created_at': self.now - 60,
            'title': '旧版提醒',
            'body': '旧提醒原始消息',
            'kind': 'screen',
            'dedup': 'legacy-event',
            'status': 'accepted',
            'attempts': 1,
            'url': 'guanlan://alerts/' + legacy_id,
        })
        self.store.save(state)

        detail = self.store.event_detail(legacy_id)

        self.assertEqual(detail['event']['body'], '旧提醒原始消息')
        self.assertIsNone(detail['report'])
        self.assertTrue(detail['message'])
        self.assertNotIn(latest_slot, detail['message'])
        restarted = RealtimeStore(self.root, lambda: self.now)
        self.assertIsNone(restarted.event_detail(legacy_id)['report'])

    def test_history_returns_the_newest_ninety_summaries_after_restart(self):
        dates = pd.bdate_range('20260105', periods=95).strftime('%Y%m%d').tolist()
        self.store.calendar(['20260102', *dates, '20260601'])
        slots = []
        for date in dates:
            parsed = datetime.strptime(date, '%Y%m%d').replace(tzinfo=ZONE, hour=14, minute=30)
            self.now = parsed.timestamp()
            job = self.store.claim('mac')
            self.assertIsNotNone(job)
            self.assertTrue(self.store.publish(job['lease'], self.report(job, '完整筛选 ' + date)))
            slots.append(job['id'])

        restarted = RealtimeStore(self.root, lambda: self.now)
        summaries = restarted.history()

        self.assertEqual(len(summaries), 90)
        self.assertEqual(summaries[0]['slot'], slots[-1])
        self.assertEqual(summaries[-1]['slot'], slots[-90])
        self.assertEqual(summaries[0]['strategy_counts'], {'overnight': 0, 'golden': 0})
        required = {'slot', 'date', 'generated_at', 'kind', 'status', 'message', 'executor', 'strategy_counts'}
        self.assertTrue(all(required.issubset(row) for row in summaries))

    def test_retired_run_preserves_original_event_text_without_rebinding(self):
        first=self.publish_scheduled(14,30,'最早轮次')
        event=self.store.state()['events'][-1]
        with patch('mobile_server.realtime_history.MAX_RUNS',2):
            self.publish_scheduled(14,45,'中间轮次')
            self.publish_scheduled(14,50,'最新轮次')
        self.assertEqual(len(list((self.store.root/'run-archive').glob('*.json'))),2)
        detail=self.store.event_detail(event['id'])
        self.assertEqual(detail['event']['body'],event['body'])
        self.assertIsNone(detail['report'])
        self.assertNotIn(first,detail['message'])


if __name__ == '__main__':
    unittest.main()
