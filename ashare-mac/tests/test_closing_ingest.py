import hashlib
import io
import json
import os
import shutil
import tempfile
import unittest
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from deployment.publish import verify
from engine.close_proof import make_attestation
from engine.snapshot_protocol import FILE_NAMES, revision_for
from mobile_server.artifacts import STRATEGIES
from mobile_server.ingest import activate, extract
from mobile_server.queue import JobQueue
from tests.test_close_proof import DATE, NOW, frames


class FrozenDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW if tz is not None else NOW.replace(tzinfo=None)


def parquet_bytes(frame):
    output = io.BytesIO()
    frame.to_parquet(output, index=False)
    return output.getvalue()


def market_entries(values):
    tables = dict(values)
    tables['stock_basic'] = values['daily'][['ts_code']].assign(
        name='测试股票', industry='测试行业', list_date='20000101')
    tables['trade_cal'] = pd.DataFrame(
        {'exchange': ['SSE'], 'cal_date': [DATE], 'is_open': [1]})
    entries = {f'market/raw/{kind}.parquet': parquet_bytes(table)
               for kind, table in tables.items()}
    manifest = {'schema_version': 1, 'as_of': DATE, 'files': [
        {'name': name, 'bytes': len(entries['market/raw/' + name]),
         'rows': len(tables[name.removesuffix('.parquet')]),
         'sha256': hashlib.sha256(entries['market/raw/' + name]).hexdigest()}
        for name in FILE_NAMES]}
    manifest['revision'] = revision_for(manifest)
    entries['market/manifest.json'] = json.dumps(manifest, separators=(',', ':')).encode()
    return entries, manifest


class ClosingIngestTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve() / 'mobile'
        self.market_root = Path(self.temporary.name).resolve() / 'market'
        for path in [self.root / 'work', self.root / 'incoming',
                     self.market_root / 'staging', self.market_root / 'releases']:
            path.mkdir(parents=True)

        self.intraday = frames()
        self.closing = {kind: frame.copy() for kind, frame in self.intraday.items()}
        self.closing['daily']['close'] = 10.1
        self.proof = make_attestation(DATE, self.closing, NOW)

        source_entries, source_manifest = market_entries(self.intraday)
        source_release = self.market_root / 'releases' / source_manifest['revision']
        self._write_market(source_release, source_entries)
        (self.market_root / 'current').symlink_to(
            Path('releases') / source_manifest['revision'])
        self.source_revision = source_manifest['revision']

        closing_entries, closing_manifest = market_entries(self.closing)
        self.data_revision = closing_manifest['revision']
        self.generation = DATE + 'T161100-abcdef'
        self.entries = dict(closing_entries)
        self.metadata = {
            'schema_version': 1,
            'input_revision': self.source_revision,
            'data_revision': self.data_revision,
            'generation': self.generation,
            'expected_as_of': DATE,
            'close_attestation': self.proof,
        }
        self.entries['bundle.json'] = self._json(self.metadata)
        codes = self.closing['daily'].ts_code.tolist()
        for strategy in STRATEGIES:
            report = {
                'schema_version': 1,
                'strategy_id': strategy,
                'as_of': DATE,
                'data_revision': self.data_revision,
                'stocks': [{'ts_code': code} for code in codes],
                'last_update': {
                    'forced_latest_date': DATE,
                    'closing_generation': DATE + '-' + 'a' * 12,
                    'close_attestation': self.proof,
                },
            }
            for code in codes:
                self.entries[f'research/{strategy}/details/{code}.json']=self._json({'ts_code':code})
            raw = self._json(report)
            self.entries[f'research/{strategy}/report.json'] = raw
            self.entries[f'research/{strategy}/manifest.json'] = self._json({
                'schema_version': 1,
                'strategy': strategy,
                'generation': self.generation,
                'as_of': DATE,
                'data_revision': self.data_revision,
                'stock_count': len(codes),
                'report_bytes': len(raw),
                'report_sha256': hashlib.sha256(raw).hexdigest(),
            })
        for code in codes:
            self.entries[f'research/charts/{code}.json'] = self._json([{'date': DATE}])

        self.archive = self.root / 'incoming' / 'closing.zip'
        self.queue = JobQueue(self.root / 'jobs', clock=lambda: NOW.timestamp())
        self.queue.submit('refresh', str(uuid.uuid4()), expected_as_of=DATE)
        self.job = self.queue.claim('mac')

    def tearDown(self):
        self.temporary.cleanup()

    @staticmethod
    def _json(value):
        return json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode()

    @staticmethod
    def _write_market(destination, entries):
        (destination / 'raw').mkdir(parents=True)
        (destination / 'manifest.json').write_bytes(entries['market/manifest.json'])
        for name in FILE_NAMES:
            (destination / 'raw' / name).write_bytes(entries['market/raw/' + name])

    def _write_bundle(self):
        with zipfile.ZipFile(self.archive, 'w', zipfile.ZIP_STORED) as output:
            for name, data in self.entries.items():
                output.writestr(name, data)

    def _ready(self):
        self._write_bundle()
        data = self.archive.read_bytes()
        self.assertTrue(self.queue.uploaded(
            self.job['id'], self.job['lease'], hashlib.sha256(data).hexdigest(), len(data)))

    def _publish_market_locally(self, root, revision):
        stage = root / 'staging' / revision
        verify(stage, revision)
        release = root / 'releases' / revision
        os.rename(stage, release)
        pointer = root / '.current-test'
        pointer.symlink_to(Path('releases') / revision)
        os.replace(pointer, root / 'current')

    def _assert_rejected_before_market_publish(self, message=None):
        self._ready()
        publisher = patch('mobile_server.ingest.publish_market').start()
        self.addCleanup(patch.stopall)
        context = self.assertRaisesRegex(ValueError, message) if message else self.assertRaises(ValueError)
        with patch('engine.close_proof.datetime', FrozenDateTime), context:
            activate(self.archive, self.root, self.market_root, self.queue, self.job)
        publisher.assert_not_called()

    def test_valid_closing_bundle_extracts_and_activates_with_a_durable_receipt(self):
        self._write_bundle()
        extracted = (Path(self.temporary.name) / 'extracted').resolve()
        extracted.mkdir()
        with patch('engine.close_proof.datetime', FrozenDateTime):
            self.assertEqual(extract(self.archive, extracted), self.metadata)
        shutil.rmtree(extracted)

        self._ready()
        with (patch('engine.close_proof.datetime', FrozenDateTime),
              patch('mobile_server.ingest.publish_market', side_effect=self._publish_market_locally),
              patch('mobile_server.ingest.time.time', return_value=NOW.timestamp())):
            result = activate(self.archive, self.root, self.market_root, self.queue, self.job)

        self.assertEqual(result, self.metadata)
        state = self.queue.state()
        self.assertEqual(state['status'], 'completed')
        self.assertEqual(state['purpose'], 'daily_review')
        self.assertEqual(state['expected_as_of'], DATE)
        self.assertEqual((self.root / 'current').resolve().name, self.generation)
        self.assertEqual((self.market_root / 'current').resolve().name, self.data_revision)
        self.assertTrue(pd.read_parquet(
            self.market_root / 'current/raw/daily.parquet').close.eq(10.1).all())
        self.assertTrue(pd.read_parquet(
            self.market_root / 'releases' / self.source_revision / 'raw/daily.parquet').close.eq(10.).all())

        receipt = json.loads((self.root / 'jobs/closing-receipts' / (DATE + '.json')).read_text())
        self.assertEqual(receipt, {
            'schema_version': 1,
            'date': DATE,
            'generation': self.generation,
            'data_revision': self.data_revision,
            'close_attestation': self.proof,
            'job_id': self.job['id'],
            'published_at': NOW.timestamp(),
        })

    def test_tampered_bundle_proof_is_rejected_before_market_publication(self):
        metadata = json.loads(self.entries['bundle.json'])
        metadata['close_attestation']['tables']['daily']['sha256'] = '0' * 64
        self.entries['bundle.json'] = self._json(metadata)
        self._assert_rejected_before_market_publish('收盘证明与实际数据不一致')

    def test_one_report_with_a_different_proof_is_rejected_before_market_publication(self):
        name = 'research/left_rebound/report.json'
        report = json.loads(self.entries[name])
        report['last_update']['close_attestation']['tables']['daily']['sha256'] = '0' * 64
        raw = self._json(report)
        self.entries[name] = raw
        manifest_name = 'research/left_rebound/manifest.json'
        manifest = json.loads(self.entries[manifest_name])
        manifest.update(report_bytes=len(raw), report_sha256=hashlib.sha256(raw).hexdigest())
        self.entries[manifest_name] = self._json(manifest)
        self._assert_rejected_before_market_publish('Research closing evidence differs')

    def test_changed_target_day_with_updated_outer_hashes_still_fails_the_original_proof(self):
        daily_name = 'market/raw/daily.parquet'
        daily = pd.read_parquet(io.BytesIO(self.entries[daily_name]))
        daily.loc[0, 'close'] = 10.2
        self.entries[daily_name] = parquet_bytes(daily)

        manifest = json.loads(self.entries['market/manifest.json'])
        record = next(item for item in manifest['files'] if item['name'] == 'daily.parquet')
        record.update(bytes=len(self.entries[daily_name]),
                      sha256=hashlib.sha256(self.entries[daily_name]).hexdigest())
        manifest['revision'] = revision_for(manifest)
        self.entries['market/manifest.json'] = self._json(manifest)

        metadata = json.loads(self.entries['bundle.json'])
        metadata['data_revision'] = manifest['revision']
        self.entries['bundle.json'] = self._json(metadata)
        for strategy in STRATEGIES:
            report_name = f'research/{strategy}/report.json'
            report = json.loads(self.entries[report_name])
            report['data_revision'] = manifest['revision']
            raw = self._json(report)
            self.entries[report_name] = raw
            manifest_name = f'research/{strategy}/manifest.json'
            report_manifest = json.loads(self.entries[manifest_name])
            report_manifest.update(data_revision=manifest['revision'], report_bytes=len(raw),
                                   report_sha256=hashlib.sha256(raw).hexdigest())
            self.entries[manifest_name] = self._json(report_manifest)

        self._assert_rejected_before_market_publish('收盘证明与实际数据不一致')
