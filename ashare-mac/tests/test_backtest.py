import unittest
from engine.backtest import evaluate_event


class BacktestTests(unittest.TestCase):
    def setUp(self):
        self.dates = [f'202601{d:02d}' for d in range(5, 17)]
        self.quotes = {(d, '000001.SZ'): dict(open=10., high=10.2, low=9.8, close=10.,
            pre_close=10., vol=100., adj_factor=1., up_limit=11., down_limit=9.) for d in self.dates}

    def run_event(self, h=3):
        return evaluate_event('000001.SZ', self.dates[0], h, self.dates, self.quotes)

    def test_signal_executes_next_open_and_holds_three_sessions(self):
        r = self.run_event()
        self.assertEqual(r['entry_date'], self.dates[1])
        self.assertEqual(r['exit_date'], self.dates[4])
        self.assertAlmostEqual(r['net_return'], -.003)

    def test_one_day_respects_t_plus_one(self):
        r = self.run_event(1)
        self.assertEqual(r['exit_date'], self.dates[2])

    def test_limit_up_entry_is_not_assumed_filled(self):
        self.quotes[self.dates[1], '000001.SZ']['open'] = 11.
        self.assertEqual(self.run_event()['status'], 'limit_up')

    def test_gap_above_three_percent_is_skipped(self):
        self.quotes[self.dates[1], '000001.SZ']['open'] = 10.4
        self.assertEqual(self.run_event()['status'], 'gap')

    def test_limit_down_delays_exit(self):
        self.quotes[self.dates[4], '000001.SZ']['open'] = 9.
        r = self.run_event()
        self.assertEqual(r['exit_date'], self.dates[5])
        self.assertEqual(r['delay'], 1)

    def test_unresolved_loser_remains_visible(self):
        for d in self.dates[4:]:
            self.quotes[d, '000001.SZ']['open'] = 9.
        self.assertEqual(self.run_event()['status'], 'unresolved')

    def test_split_does_not_create_fake_loss(self):
        for d in self.dates[2:]:
            for k in ['open', 'high', 'low', 'close', 'pre_close', 'up_limit', 'down_limit']:
                self.quotes[d, '000001.SZ'][k] /= 2
            self.quotes[d, '000001.SZ']['adj_factor'] = 2.
        self.assertAlmostEqual(self.run_event()['net_return'], -.003)

    def test_missing_limits_fail_closed(self):
        self.quotes[self.dates[1], '000001.SZ']['up_limit'] = None
        self.assertEqual(self.run_event()['status'], 'missing_entry')

    def test_absent_market_session_does_not_shift_entry(self):
        del self.quotes[self.dates[1], '000001.SZ']
        self.assertEqual(self.run_event()['status'], 'missing_entry')

    def test_invalid_horizon_rejected(self):
        with self.assertRaises(ValueError):
            self.run_event(0)
