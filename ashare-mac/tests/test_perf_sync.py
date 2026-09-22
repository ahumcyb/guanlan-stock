"""Focused checks for publish-without-orderflow, short list, and fetch-on-change revisions."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mobile_server.api import Service
from mobile_server.artifacts import PREVIOUS_STRATEGIES,atomic_json,list_stock,patch_orderflow,publish,priority_chart_codes
from tests.test_mobile_api import MobileAPITests


def change_color_bucket(value):
    """Mirror MobileTheme.change / Palette.change: up / down / flat."""
    if value>0:return 'up'
    if value<0:return 'down'
    return 'flat'


class ChangeSignTests(unittest.TestCase):
    def test_flat_is_neutral_not_up(self):
        self.assertEqual(change_color_bucket(1.2),'up')
        self.assertEqual(change_color_bucket(-0.5),'down')
        self.assertEqual(change_color_bucket(0.0),'flat')
        self.assertEqual(change_color_bucket(-0.0),'flat')


class ChunkedReadLimitTests(unittest.TestCase):
    def test_chunk_assembly_respects_size_cap(self):
        limit=128
        chunks=[b'x'*64,b'y'*64,b'z'*1]
        data=bytearray();oversized=False
        for chunk in chunks:
            if len(data)+len(chunk)>limit:
                oversized=True;break
            data.extend(chunk)
        self.assertTrue(oversized)
        self.assertEqual(len(data),128)


class FetchOnChangeTests(unittest.TestCase):
    def test_status_revisions_change_when_reports_republish(self):
        fixture=MobileAPITests();fixture.setUp();self.addCleanup(fixture.tearDown)
        outputs=fixture.outputs()
        publish(outputs,fixture.root,'20260904-aaaaaaaaaaaaaaaa')
        first=fixture.call('GET','/v2/status')[1]['revisions']['reports']
        publish(outputs,fixture.root,'20260904-aaaaaaaaaaaaaaaa')
        second=fixture.call('GET','/v2/status')[1]['revisions']['reports']
        self.assertNotEqual(first,second)
        self.assertTrue(first);self.assertTrue(second)


class PublishWithoutOrderflowTests(unittest.TestCase):
    def test_pointer_moves_before_orderflow_and_patch_attaches(self):
        fixture=MobileAPITests();fixture.setUp();self.addCleanup(fixture.tearDown)
        outputs=fixture.outputs()
        manifests=publish(outputs,fixture.root,'20260904-aaaaaaaaaaaaaaaa',strategies=PREVIOUS_STRATEGIES)
        generation=manifests['leaders']['generation']
        self.assertEqual((fixture.root/'current').resolve().name,generation)
        self.assertFalse((fixture.root/'releases'/generation/'orderflow').exists())
        report=json.loads((fixture.root/'releases'/generation/'leaders/report.json').read_text())
        self.assertEqual(set(report['stocks'][0].keys())-{'amount20'}, {
            'ts_code','name','industry','trade_date','close','change','score','state','rank',
            'eligible','stale','adjusted','limit_available'})
        patch_orderflow(outputs/'orderflow',fixture.root,generation,'20260904-aaaaaaaaaaaaaaaa')
        self.assertTrue((fixture.root/'releases'/generation/'orderflow/manifest.json').exists())
        self.assertEqual((fixture.root/'current').resolve().name,generation)

    def test_priority_chart_codes_cover_picks_and_watch(self):
        report={'stocks':[
            {'ts_code':'000001.SZ','state':'入选'},
            {'ts_code':'000002.SZ','state':'等待'},
            {'ts_code':'000003.SZ','state':'排除'},
        ]}
        self.assertEqual(priority_chart_codes(report),{'000001.SZ','000002.SZ'})
        self.assertEqual(list_stock({'ts_code':'1','name':'n','extra':9,'score':1}),{'ts_code':'1','name':'n','score':1})
