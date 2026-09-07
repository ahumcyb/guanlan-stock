import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from mobile_server.build import build


class ClosingBuildTests(unittest.TestCase):
    def test_day_refresh_passes_target_and_does_not_build_from_missing_attestation(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'market';root.mkdir();(root/'manifest.json').write_text('{}')
            overlay=Path(folder)/'overlay';overlay.mkdir()
            calls=[]
            def run(args,**kwargs):
                calls.append(args)
                self.assertEqual(args[3],'engine.update')
                used_overlay=Path(args[args.index('--overlay')+1])
                (used_overlay/'last_update.json').write_text(json.dumps({'through':'20260904','validation':'partial','close_attestation':None}))
            with patch('mobile_server.build.validate_manifest',return_value={'revision':'20260904-aaaaaaaaaaaaaaaa'}),patch('mobile_server.build.subprocess.run',side_effect=run):
                with self.assertRaises(ValueError):build(root,overlay,Path(folder)/'work','refresh',expected_as_of='20260904')
            self.assertEqual(len(calls),1)
            self.assertIn('--force-latest',calls[0])
            index=calls[0].index('--through');self.assertEqual(calls[0][index+1],'20260904')
