import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from engine.market_clock import market_status


ZONE = ZoneInfo('Asia/Shanghai')


def at(year, month, day, hour, minute, second=0):
    return datetime(year, month, day, hour, minute, second, tzinfo=ZONE)


class MarketStatusTests(unittest.TestCase):
    def assert_status(self, value, now, expected_as_of, phase, covered=True):
        self.assertEqual(value['expected_as_of'], expected_as_of)
        self.assertEqual(value['phase'], phase)
        self.assertIs(value['calendar_covered'], covered)
        self.assertEqual(value['checked_at'], now.timestamp())

    def test_monday_before_open_expects_fridays_complete_daily_bar(self):
        now = at(2026, 9, 7, 8, 45)
        value = market_status(['20260904', '20260907', '20260908'], now)
        self.assert_status(value, now, '20260904', 'before_open')

    def test_trading_session_does_not_require_the_current_daily_bar(self):
        now = at(2026, 9, 7, 14, 45)
        value = market_status(['20260904', '20260907', '20260908'], now)
        self.assert_status(value, now, '20260904', 'trading')

    def test_exactly_fifteen_ten_switches_expected_daily_bar_to_today(self):
        just_before = at(2026, 9, 7, 15, 9, 59)
        at_cutoff = at(2026, 9, 7, 15, 10)
        dates = ['20260904', '20260907', '20260908']

        self.assert_status(market_status(dates, just_before), just_before, '20260904', 'trading')
        self.assert_status(market_status(dates, at_cutoff), at_cutoff, '20260907', 'after_close')

    def test_weekend_uses_friday_and_reports_closed_market(self):
        now = at(2026, 9, 12, 12, 0)
        value = market_status(['20260910', '20260911', '20260914'], now)
        self.assert_status(value, now, '20260911', 'closed')

    def test_calendar_without_today_or_a_future_session_is_unknown(self):
        now = at(2026, 9, 7, 10, 0)
        value = market_status(['20260903', '20260904'], now)
        self.assert_status(value, now, None, 'unknown', covered=False)


if __name__ == '__main__':
    unittest.main()
