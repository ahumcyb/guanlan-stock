import json
import tempfile
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from mobile_server.watchlist import WatchlistStore
from mobile_server.api import Service,Failure


def operation(code,action='add'):
    return dict(operation_id=str(uuid.uuid4()),ts_code=code,action=action)


class WatchlistTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name).resolve()
        self.store=WatchlistStore(self.root)
    def tearDown(self):self.tmp.cleanup()

    def test_independent_devices_merge_instead_of_replacing_the_whole_list(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(self.store.apply,[operation('000001.SZ'),operation('600519.SH')]))
        self.assertEqual(self.store.public()['codes'],['000001.SZ','600519.SH'])
        self.store.apply(operation('000001.SZ','remove'))
        self.assertEqual(WatchlistStore(self.root).public()['codes'],['600519.SH'])

    def test_lost_add_response_replay_does_not_undo_a_later_remove(self):
        add=operation('000001.SZ');self.store.apply(add)
        removed=self.store.apply(operation('000001.SZ','remove'))
        replay=self.store.apply(add)
        self.assertEqual(replay['codes'],[])
        self.assertEqual(replay['revision'],removed['revision'])
        with self.assertRaises(ValueError):self.store.apply(dict(add,action='remove'))

    def test_invalid_input_cannot_change_saved_state(self):
        self.store.apply(operation('600519.SH'))
        for change in [dict(operation('600519.SH'),action='replace'),operation('../../x'),
                       dict(operation('600519.SH'),codes=[]),dict(operation('600519.SH'),operation_id='bad')]:
            with self.subTest(change=change),self.assertRaises(ValueError):self.store.apply(change)
        self.assertEqual(self.store.public()['codes'],['600519.SH'])

    def test_api_only_viewer_can_read_or_change_watchlist(self):
        service=Service(self.root,'a'*64,'b'*64)
        for auth in ['', 'Bearer '+'b'*64]:
            with self.assertRaises(Failure):service.dispatch('GET','/v1/watchlist',auth)
        value=operation('000001.SZ')
        self.assertEqual(service.dispatch('POST','/v1/watchlist','Bearer '+'a'*64,json.dumps(value).encode())[1]['codes'],['000001.SZ'])
        self.assertEqual(service.dispatch('GET','/v1/watchlist','Bearer '+'a'*64)[1]['schema_version'],1)
