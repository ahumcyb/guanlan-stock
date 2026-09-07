import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from mobile_server.api import Service,Failure


class DailyAPITests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.service=Service(self.root,'a'*64,'b'*64);self.auth='Bearer '+'a'*64
    def tearDown(self):self.tmp.cleanup()

    def test_public_settings_mask_shared_key_and_worker_cannot_change_it(self):
        code,result=self.service.dispatch('POST','/v1/daily/settings',self.auth,
            json.dumps({'enabled':True,'deepseek_key':'test-key-not-production'}).encode())
        self.assertEqual(code,200);self.assertTrue(result['deepseek_configured'])
        code,state=self.service.dispatch('GET','/v1/daily',self.auth)
        self.assertEqual(code,200);self.assertNotIn('test-key-not-production',json.dumps(state))
        with self.assertRaises(Failure):self.service.dispatch('POST','/v1/daily/settings','Bearer '+'b'*64,b'{}')

    def test_bad_dates_and_arbitrary_configuration_are_rejected(self):
        for target in ['/v1/daily/20260230','/v1/daily/../settings']:
            with self.assertRaises(Failure):self.service.dispatch('GET',target,self.auth)
        with self.assertRaises(Failure):self.service.dispatch('POST','/v1/daily/settings',self.auth,b'{"base_url":"http://localhost"}')

    def test_api_import_does_not_load_dataframe_runtimes_or_call_a_provider(self):
        result=subprocess.run([sys.executable,'-c','import sys; import mobile_server.api; assert "pandas" not in sys.modules and "pyarrow" not in sys.modules'],capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr.decode())
