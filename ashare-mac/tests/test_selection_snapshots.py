import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from tests.test_daily_facts import published_fixture
from tests.test_close_proof import DATE,NOW
from mobile_server.selection_snapshots import read_legacy_generation,find_previous_snapshot,save_snapshot,read_snapshot


class SelectionSnapshotTests(unittest.TestCase):
    def test_verified_preceding_generation_is_preserved_and_cannot_be_rewritten(self):
        with tempfile.TemporaryDirectory() as folder:
            root,_=published_fixture(folder);generation=DATE+'T161100-abcdef'
            value=read_legacy_generation(root,generation,DATE)
            found=find_previous_snapshot(root,DATE,'20260907')
            self.assertEqual(found,value)
            changed=[dict(group,picks=[dict(pick,close=99.) for pick in group['picks']]) for group in value['strategies']]
            with self.assertRaises(ValueError):save_snapshot(root,DATE,generation,value['data_revision'],changed)
            path=root/'jobs/daily/selections'/DATE/(generation+'.json')
            self.assertEqual(read_snapshot(path.parent,path),value)

    def test_late_publication_cannot_be_reinterpreted_as_a_legacy_early_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            root,_=published_fixture(folder);path=root/'jobs/closing-receipts'/(DATE+'.json')
            receipt=json.loads(path.read_text())
            receipt['published_at']=datetime(2026,9,7,10,tzinfo=ZoneInfo('Asia/Shanghai')).timestamp()
            path.write_text(json.dumps(receipt))
            self.assertIsNone(find_previous_snapshot(root,DATE,'20260907'))

    def test_original_closing_receipt_can_import_prior_selection_without_daily_summary(self):
        with tempfile.TemporaryDirectory() as folder:
            root,_=published_fixture(folder)
            value=find_previous_snapshot(root,DATE,'20260907')
            self.assertEqual(value['timing_basis'],'closing_receipt')
            self.assertEqual(value['published_at'],NOW.timestamp())
            self.assertEqual(len(value['strategies']),5)

    def test_corrupt_saved_snapshot_does_not_silently_fall_back_to_another_version(self):
        with tempfile.TemporaryDirectory() as folder:
            root,_=published_fixture(folder);value=find_previous_snapshot(root,DATE,'20260907')
            path=root/'jobs/daily/selections'/DATE/(value['generation']+'.json')
            envelope=json.loads(path.read_text());envelope['snapshot']['strategies'][0]['picks'][0]['close']=999.
            path.write_text(json.dumps(envelope))
            with self.assertRaises(ValueError):find_previous_snapshot(root,DATE,'20260907')
