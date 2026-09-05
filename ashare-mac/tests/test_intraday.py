import unittest
from datetime import timedelta
from engine.intraday import local_now, due_slot, trading_minutes, normalize_quote, screen, minute_pattern


class IntradayTests(unittest.TestCase):
    def setUp(self):
        self.now = local_now().replace(year=2026, month=9, day=4, hour=14, minute=50, second=0, microsecond=0)
        self.row = dict(ts_code='600000.SH', open=10, high=10.5, low=10, close=10.4, pre_close=10,
                        vol=180000000, amount=1850000000, trade_time='20260904', updated_at='2026-09-04T14:49:59.000')

    def test_calendar_and_catchup_window(self):
        self.assertEqual(due_slot(self.now, {'20260904'})['id'], '20260904-1450')
        self.assertIsNone(due_slot(self.now, set()))
        self.assertIsNone(due_slot(self.now + timedelta(minutes=3), {'20260904'}))
        self.assertEqual(trading_minutes(self.now.replace(hour=13, minute=0)), 120)
        self.assertEqual(trading_minutes(self.now), 230)

    def test_provider_timestamp_is_not_trade_timestamp(self):
        q = normalize_quote(self.row, self.now)
        self.assertEqual(q['time_basis'], 'provider_updated_at')
        self.assertEqual(q['vol'], 180000000)  # rt_k is shares, not daily's lots.
        self.assertAlmostEqual(q['change'], 4)
        for changes in [dict(updated_at=None), dict(updated_at='2026-09-03T14:50:00'),
                        dict(updated_at='2026-09-04T14:53:00'), dict(trade_time='20260903'), dict(vol=0), dict(close=float('nan'))]:
            with self.subTest(changes=changes), self.assertRaises((ValueError, TypeError)):
                normalize_quote(dict(self.row, **changes), self.now)

    def test_rules_missing_minutes_and_corporate_action(self):
        features = {'600000.SH': dict(name='浦发银行', date='20260903', observations=60, adjusted=True, last_close=10, mean_volume5=100000000,
                        sum4=40, sum9=87, sum19=175, ma5=9.9, platform_range=1.1, platform_high=11, float_shares=2000000000)}
        q = normalize_quote(self.row, self.now)
        result = screen(features, [q], {'change': 0, 'quote_at': self.now.timestamp()}, self.now, '20260903')
        self.assertEqual(len(result['overnight']), 1)
        # Shares imply cap >200bn? Here 208yi exceeds 200yi and must be excluded.
        self.assertEqual(len(result['golden']), 0)
        features['600000.SH']['float_shares'] = 1900000000
        result = screen(features, [q], {'change': 0, 'quote_at': self.now.timestamp()}, self.now, '20260903')
        self.assertEqual(result['golden'][0]['state'], '待分时核验')
        self.assertEqual(len(result['golden'][0]['pending']), 4)
        self.assertFalse(screen(features, [q], {'change': -.31, 'quote_at': self.now.timestamp()}, self.now, '20260903')['overnight'])
        features['600000.SH']['last_close'] = 12
        self.assertFalse(screen(features, [q], {'change': 0, 'quote_at': self.now.timestamp()}, self.now, '20260903')['overnight'])

    def test_boundary_volume_and_no_fake_minute_confirmation(self):
        self.assertIsNone(minute_pattern([], self.now))
        f = {'600000.SH': dict(name='浦发银行', date='20260903', observations=60, adjusted=True, last_close=10, mean_volume5=120000000,
             sum4=40, sum9=87, sum19=175, ma5=9.9, platform_range=1.1, platform_high=11)}
        q = normalize_quote(self.row, self.now)
        self.assertEqual(len(screen(f, [q], {'change': -.3, 'quote_at': self.now.timestamp()}, self.now, '20260903')['overnight']), 1)
        q['vol'] -= 1
        self.assertFalse(screen(f, [q], {'change': 0, 'quote_at': self.now.timestamp()}, self.now, '20260903')['overnight'])

    def test_feature_date_missing_fields_and_bad_index(self):
        f = {'600000.SH': dict(name='浦发银行', date='20260903', observations=60, adjusted=True, last_close=10,
             mean_volume5=100000000, sum4=40, sum9=87, sum19=175, ma5=9.9, platform_range=1.1, platform_high=11, float_shares=1900000000)}
        q = normalize_quote(self.row, self.now)
        for index in [{'change': float('nan'), 'quote_at': self.now.timestamp()}, {'change': 0, 'quote_at': self.now.timestamp()-181}]:
            result = screen(f, [q], index, self.now, '20260903')
            self.assertFalse(result['overnight']);self.assertTrue(result['golden'])
        for changes in [{'date': '20260902'}, {'observations': 59}, {'adjusted': False}, {'sum4': None}]:
            broken = {'600000.SH': dict(f['600000.SH'], **changes)}
            self.assertFalse(any(screen(broken, [q], {'change': 0, 'quote_at': self.now.timestamp()}, self.now, '20260903').values()))
        with self.assertRaises(ValueError):
            normalize_quote(dict(self.row, vol=self.row['vol']/100), self.now)

    def test_minute_grid_pullback_and_unit_reconciliation(self):
        rows = []
        for minute in list(range(571, 691)) + list(range(781, 891)):
            late = minute >= 885
            price = 10.4 if minute == 885 else (10.35 if late else 10.2)
            t = self.now.replace(hour=minute//60, minute=minute%60)
            rows.append(dict(time=t.isoformat(), close=price, high=price, vol=1000, amount=10200))
        quote = dict(vol=230000, amount=2346000)
        self.assertTrue(minute_pattern(rows, self.now, quote))
        below = [dict(r) for r in rows];below[-1]['close'] = 10.1
        self.assertFalse(minute_pattern(below, self.now, quote))
        self.assertIsNone(minute_pattern(rows[:-30] + rows[-29:], self.now, quote))
        self.assertIsNone(minute_pattern(rows, self.now, dict(vol=2300, amount=2346000)))
        bad = [dict(r) for r in rows];bad[2]['time'] = bad[2]['time'].replace(':00+', ':30+')
        self.assertIsNone(minute_pattern(bad, self.now, quote))
        lunch = rows + [dict(rows[0], time=self.now.replace(hour=12, minute=0).isoformat())]
        self.assertIsNone(minute_pattern(lunch, self.now, quote))


if __name__ == '__main__':
    unittest.main()
