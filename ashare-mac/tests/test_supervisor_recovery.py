import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mobile_server import datta_supervisor


class SupervisorRecoveryTests(unittest.TestCase):
    def test_unconfirmed_shutdown_never_starts_a_second_native_client(self):
        class StopEvent:
            def __init__(self):
                self.stopped = False

            def is_set(self):
                return self.stopped

            def set(self):
                self.stopped = True

            def wait(self, _timeout):
                return self.stopped

        stopped = StopEvent()

        class Process:
            def poll(self):
                return None

        class NativeClient:
            instance = None

            def __init__(self, _config):
                self.process = None
                self.starts = 0
                self.stops = 0
                NativeClient.instance = self

            def start(self):
                self.starts += 1
                self.process = Process()

            def stop(self):
                self.stops += 1
                if self.stops == 1:
                    return  # Initial cleanup before the ownership loop.
                if self.stops in (2, 3, 4):
                    # The managed process exited, but the local control port is
                    # still alive, so shutdown has not been acknowledged.
                    self.process = None
                    if self.stops == 3:
                        stopped.set()
                    raise ValueError('local control port is still alive')

        class WorkerClient:
            def __init__(self, _config):
                self.polls = 0

            def request(self, path, value=None):
                if path.endswith('/poll'):
                    self.polls += 1
                    return {
                        'owner': 'mac',
                        'phase': 'reserved' if self.polls < 3 else 'active',
                        'epoch': 1,
                        'token': 'a' * 64,
                        'lease_until': 10_000,
                    }
                return {'accepted': True}

        statuses = iter([
            {'exeConnected': True, 'isLoggedIn': True, 'isVerified': True, 'running': True},
            {'exeConnected': False, 'isLoggedIn': False, 'isVerified': False, 'running': False},
        ])

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            worker_config = root / 'worker.json'
            worker_config.write_text(json.dumps({'test': True}))
            config = {
                'node': 'mac',
                'receipt': str(root / 'receipt.json'),
                'worker_config': str(worker_config),
            }
            with (
                patch.object(datta_supervisor.threading, 'Event', return_value=stopped),
                patch.object(datta_supervisor, 'NativeClient', NativeClient),
                patch('mobile_server.mac_worker.WorkerClient', WorkerClient),
                patch.object(datta_supervisor, 'admin', side_effect=lambda _action: next(statuses)),
                patch.object(datta_supervisor, 'log_event'),
                patch.object(datta_supervisor.signal, 'signal'),
            ):
                datta_supervisor.serve(config)

        self.assertEqual(NativeClient.instance.starts, 1)
        self.assertGreaterEqual(NativeClient.instance.stops, 4)


if __name__ == '__main__':
    unittest.main()
