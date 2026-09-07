import hashlib
import json
import tempfile
import time
import unittest
import uuid
import os
from pathlib import Path
from unittest.mock import patch
from mobile_server.api import Service,Failure
from mobile_server.artifacts import atomic_json,publish,current_manifest


class MobileAPITests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve()
        self.service=Service(self.root,'a'*64);self.auth='Bearer '+'a'*64
        atomic_json(self.root/'jobs/capabilities.json',{'heartbeat':time.time(),'can_refresh':True})

    def tearDown(self):self.temp.cleanup()

    def call(self,method,path,body=None):return self.service.dispatch(method,path,self.auth,json.dumps(body).encode() if body is not None else b'')

    def test_health_contains_no_private_metadata_and_business_requires_auth(self):
        self.assertEqual(self.service.dispatch('GET','/health',''),(200,{'status':'ok'}))
        with self.assertRaises(Failure) as error:self.service.dispatch('GET','/v1/status','Bearer wrong')
        self.assertEqual(error.exception.status,401)

    def test_traversal_and_url_parameters_are_rejected(self):
        for path in ['/v1/reports/../secret','/v1/%2e%2e/secret','/v1/status?token=anything']:
            with self.assertRaises(Failure) as error:self.call('GET',path)
            self.assertEqual(error.exception.status,400)

    def test_job_requests_are_idempotent_and_single_flight(self):
        value={'action':'refresh','request_id':str(uuid.uuid4())}
        code,first=self.call('POST','/v1/jobs',value)
        self.assertEqual(code,202)
        self.assertEqual(self.call('POST','/v1/jobs',value)[1]['id'],first['id'])
        self.assertEqual(self.call('POST','/v1/jobs',{'action':'recompute','request_id':str(uuid.uuid4())})[1]['id'],first['id'])

    def test_worker_offline_cannot_accept_new_job(self):
        atomic_json(self.root/'jobs/capabilities.json',{'heartbeat':0})
        with self.assertRaises(Failure) as error:self.call('POST','/v1/jobs',{'action':'refresh','request_id':str(uuid.uuid4())})
        self.assertEqual(error.exception.status,503)

    def test_arbitrary_actions_and_extra_fields_are_rejected(self):
        with self.assertRaises(Failure):self.call('POST','/v1/jobs',{'action':'rm -rf /','request_id':str(uuid.uuid4())})
        with self.assertRaises(Failure):self.call('POST','/v1/jobs',{'action':'refresh','request_id':str(uuid.uuid4()),'path':'/'})

    def test_cooldown_preserves_last_completed_job(self):
        old_id=str(uuid.uuid4())
        atomic_json(self.root/'jobs/status.json',{'status':'completed','created_at':time.time(),'id':old_id,'request_id':str(uuid.uuid4()),'action':'refresh','message':'完成'})
        with self.assertRaises(Failure) as error:self.call('POST','/v1/jobs',{'action':'refresh','request_id':str(uuid.uuid4())})
        self.assertEqual(error.exception.status,429);self.assertEqual(self.service.state()['id'],old_id)

    def test_worker_state_rejects_symlink_oversize_and_extra_private_fields(self):
        outside=self.root/'private.json';outside.write_text('{"secret":"not public"}')
        state=self.root/'jobs/status.json';state.symlink_to(outside)
        with self.assertRaises(ValueError):self.call('GET','/v1/status')
        state.unlink();state.write_text(' '*65537)
        with self.assertRaises(ValueError):self.call('GET','/v1/status')
        atomic_json(state,{'status':'idle','message':'ready','secret':'not public'})
        with self.assertRaises(ValueError):self.call('GET','/v1/status')

    def test_same_date_but_changed_charts_cannot_mix_strategies(self):
        outputs=self.outputs();first=publish(outputs,self.root,'20260904-aaaaaaaaaaaaaaaa')
        chart=outputs/'pullback/20260905T120000-abcdef/charts/000001.SZ.json'
        chart.write_text('[{"date":"20260904","close":999}]')
        with self.assertRaises(ValueError):publish(outputs,self.root,'20260904-aaaaaaaaaaaaaaaa')
        self.assertEqual(current_manifest(self.root,'leaders'),first['leaders'])

    def test_unbound_market_revision_and_non_uuid_requests_are_rejected(self):
        with self.assertRaises(ValueError):publish(self.outputs(),self.root,'20260904-bbbbbbbbbbbbbbbb')
        with self.assertRaises(Failure):self.call('POST','/v1/jobs',{'action':'refresh','request_id':'-'*36})

    def outputs(self):
        outputs=self.root/'outputs'
        for strategy in ['leaders','pullback','golden_pit','left_rebound']:
            folder=outputs/strategy/'20260905T120000-abcdef';(folder/'charts').mkdir(parents=True)
            report={'schema_version':1,'strategy_id':strategy,'as_of':'20260904','data_revision':'20260904-aaaaaaaaaaaaaaaa','source_root':'/private/source','overlay_root':'/private/overlay','stocks':[{'ts_code':'000001.SZ'}],'backtest':{'events':[{'event':'large'}],'horizons':[1,3,5]}}
            atomic_json(folder/'report.json',report);atomic_json(folder/'charts/000001.SZ.json',[{'date':'20260904'}])
            atomic_json(outputs/strategy/'current.json',{'generation':folder.name,'sha256':hashlib.sha256((folder/'report.json').read_bytes()).hexdigest()})
        return outputs

    def test_published_snapshots_are_pinned_and_private_paths_removed(self):
        published=publish(self.outputs(),self.root,'20260904-aaaaaaaaaaaaaaaa')
        manifest=self.call('GET','/v1/reports/leaders/current')[1]
        self.assertEqual(manifest['generation'],published['pullback']['generation'])
        path=self.call('GET',f"/v1/reports/leaders/{manifest['generation']}/report.json")[1]
        report=json.loads(path.read_text())
        self.assertNotIn('/private',path.read_text());self.assertNotIn('events',report['backtest'])
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),manifest['report_sha256'])

    def test_bad_second_strategy_cannot_replace_previous_snapshot(self):
        outputs=self.outputs();first=publish(outputs,self.root,'20260904-aaaaaaaaaaaaaaaa')
        (outputs/'pullback/20260905T120000-abcdef/report.json').write_text('{}')
        with self.assertRaises(ValueError):publish(outputs,self.root,'20260904-bbbbbbbbbbbbbbbb')
        self.assertEqual(current_manifest(self.root,'leaders'),first['leaders'])

    def test_symlinked_chart_is_never_served(self):
        publish(self.outputs(),self.root,'20260904-aaaaaaaaaaaaaaaa');manifest=current_manifest(self.root,'leaders')
        path=self.root/'releases'/manifest['generation']/'charts/000001.SZ.json'
        path.unlink();path.symlink_to(self.root/'jobs/capabilities.json')
        with self.assertRaises(ValueError):self.call('GET',f"/v1/reports/leaders/{manifest['generation']}/charts/000001.SZ.json")

    def test_golden_pit_is_served_and_its_chart_must_match(self):
        outputs=self.outputs();first=publish(outputs,self.root,'20260904-aaaaaaaaaaaaaaaa')
        manifest=self.call('GET','/v1/reports/golden_pit/current')[1]
        self.assertEqual(manifest['generation'],first['leaders']['generation'])
        chart=outputs/'golden_pit/20260905T120000-abcdef/charts/000001.SZ.json'
        chart.write_text('[{"date":"20260904","close":999}]')
        with self.assertRaises(ValueError):publish(outputs,self.root,'20260904-aaaaaaaaaaaaaaaa')
        self.assertEqual(current_manifest(self.root,'golden_pit'),first['golden_pit'])

    def test_momentum_is_served_and_bad_fourth_chart_preserves_current(self):
        outputs=self.outputs();first=publish(outputs,self.root,'20260904-aaaaaaaaaaaaaaaa')
        manifest=self.call('GET','/v1/reports/left_rebound/current')[1]
        self.assertEqual(manifest['generation'],first['leaders']['generation'])
        (outputs/'left_rebound/20260905T120000-abcdef/charts/000001.SZ.json').write_text('[]')
        with self.assertRaises(ValueError):publish(outputs,self.root,'20260904-aaaaaaaaaaaaaaaa')
        self.assertEqual(current_manifest(self.root,'left_rebound'),first['left_rebound'])

    def test_old_release_remains_readable_before_fourth_strategy_is_published(self):
        publish(self.outputs(),self.root,'20260904-aaaaaaaaaaaaaaaa')
        import shutil
        shutil.rmtree(self.root/'current/left_rebound')
        status=self.call('GET','/v1/status')[1]
        self.assertEqual(set(status['reports']),{'leaders','pullback','golden_pit'})
        self.assertEqual(self.call('GET','/v1/reports/leaders/current')[0],200)

    def test_retention_keeps_latest_historical_momentum_after_four_left_releases(self):
        generation='20260904T161100-abcdef';release=self.root/'releases'/generation
        (release/'momentum_60').mkdir(parents=True);(release/'charts').mkdir()
        report=b'{"strategy_id":"momentum_60","historical":true}'
        (release/'momentum_60/report.json').write_bytes(report)
        atomic_json(release/'momentum_60/manifest.json',{'schema_version':1,'generation':generation,
            'strategy':'momentum_60','as_of':'20260904','data_revision':'20260904-aaaaaaaaaaaaaaaa',
            'report_bytes':len(report),'report_sha256':hashlib.sha256(report).hexdigest(),'stock_count':1})
        chart=b'[{"date":"20260904","close":10}]';(release/'charts/000001.SZ.json').write_bytes(chart)
        os.utime(release,(0,0))

        outputs=self.outputs()
        with patch('mobile_server.artifacts.time.strftime',side_effect=[
                '20260905T161100','20260906T161100','20260907T161100','20260908T161100']):
            for _ in range(4):publish(outputs,self.root,'20260904-aaaaaaaaaaaaaaaa')

        manifest=current_manifest(self.root,'momentum_60')
        self.assertEqual(manifest['generation'],generation)
        report_path=self.call('GET',f'/v1/reports/momentum_60/{generation}/report.json')[1]
        chart_path=self.call('GET',f'/v1/reports/momentum_60/{generation}/charts/000001.SZ.json')[1]
        self.assertEqual(report_path.read_bytes(),report)
        self.assertEqual(chart_path.read_bytes(),chart)
