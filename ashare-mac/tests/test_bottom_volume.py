import unittest

from engine.intraday import bottom_volume_screen, local_now


NOW = local_now().replace(
    year=2026, month=9, day=8, hour=14, minute=30, second=0, microsecond=0
)
PREVIOUS = '20260907'


def feature(**changes):
    value = dict(
        name='测试股票',
        date=PREVIOUS,
        observations=60,
        adjusted=True,
        last_close=10.0,
        mean_volume5=100_000.0,
        low60=10.0,
    )
    value.update(changes)
    return value


def quote(code='600000.SH', **changes):
    close = changes.pop('close', 10.5)
    pre_close = changes.pop('pre_close', 10.0)
    value = dict(
        ts_code=code,
        name='测试股票',
        close=close,
        pre_close=pre_close,
        vol=300_000.0,
        amount=close * 300_000.0,
        change=(close / pre_close - 1) * 100,
        quote_at=NOW.timestamp(),
        time_basis='trade_time',
    )
    value.update(changes)
    return value


def run(one_feature=None, one_quote=None):
    return bottom_volume_screen(
        {'600000.SH': one_feature or feature()},
        [one_quote or quote()],
        NOW,
        PREVIOUS,
    )


class BottomVolumeTests(unittest.TestCase):
    def assert_empty(self, result):
        self.assertEqual(result['status'], 'empty')
        self.assertEqual(result['candidates'], [])
        self.assertEqual(result['matched_count'], 0)
        self.assertEqual(result['lookback'], 60)

    def test_two_point_five_times_volume_and_position_boundaries_are_inclusive(self):
        at_low = run(one_quote=quote(close=10.0, pre_close=9.99, vol=250_000.0))
        self.assertEqual(at_low['status'], 'ready')
        self.assertEqual(at_low['matched_count'], 1)
        self.assertEqual([row['ts_code'] for row in at_low['candidates']], ['600000.SH'])
        self.assertEqual(at_low['lookback'], 60)
        self.assertEqual(at_low['rule_version'], 2)

        at_ten_percent = run(one_quote=quote(close=11.0, change=10.0))
        self.assertEqual(at_ten_percent['matched_count'], 1)

        below_volume = run(one_quote=quote(vol=249_999.0, amount=10.5 * 249_999.0))
        self.assert_empty(below_volume)

    def test_below_the_prior_low_or_above_ten_percent_is_excluded(self):
        self.assert_empty(run(one_quote=quote(close=9.99, change=-0.1)))
        self.assert_empty(run(one_quote=quote(close=11.0001, change=10.001)))

    def test_only_positive_change_is_allowed_without_three_to_five_percent_limit(self):
        down = run(one_feature=feature(low60=9.0), one_quote=quote(close=9.8, change=-2.0))
        flat = run(one_quote=quote(close=10.0, change=0.0))
        small_up = run(one_quote=quote(close=10.01, vol=250_000.0))
        up = run(one_quote=quote(close=10.8, change=8.0))

        self.assert_empty(down)
        self.assert_empty(flat)
        self.assertEqual(small_up['matched_count'], 1)
        self.assertEqual(up['matched_count'], 1)

    def test_positive_change_is_calculated_from_price_and_not_rounded_to_zero(self):
        self.assert_empty(run(one_quote=quote(close=10.,change=5.)))
        result = run(one_feature=feature(low60=2900.,last_close=3000.),
                     one_quote=quote(close=3000.01,pre_close=3000.,vol=250_000.))
        self.assertEqual(result['matched_count'],1)
        self.assertGreater(result['candidates'][0]['change'],0)

    def test_stale_quote_wrong_feature_date_st_and_missing_low_are_fail_closed(self):
        cases = [
            (feature(), quote(quote_at=NOW.timestamp() - 181)),
            (feature(date='20260904'), quote()),
            (feature(name='ST 测试'), quote()),
            (feature(), quote(name='*ST 测试')),
            (feature(low60=None), quote()),
            (feature(observations=59), quote()),
            (feature(adjusted=False), quote()),
        ]
        for one_feature, one_quote in cases:
            with self.subTest(feature=one_feature, quote=one_quote):
                self.assert_empty(run(one_feature=one_feature, one_quote=one_quote))

    def test_reference_price_discontinuity_is_excluded(self):
        discontinuous = quote(pre_close=10.04, close=10.5)
        self.assert_empty(run(one_quote=discontinuous))

    def test_thirteen_matches_report_total_but_display_only_top_ten_by_volume_multiple(self):
        features = {}
        quotes = []
        for index in range(13):
            code = f'{600000 + index:06}.SH'
            features[code] = feature(name=f'股票{index:02}')
            multiple = 3 + index
            quotes.append(quote(code, name=f'股票{index:02}', vol=100_000 * multiple,
                                amount=10.5 * 100_000 * multiple))

        result = bottom_volume_screen(features, quotes, NOW, PREVIOUS)

        self.assertEqual(result['status'], 'ready')
        self.assertEqual(result['matched_count'], 13)
        self.assertEqual(len(result['candidates']), 10)
        self.assertEqual(
            [row['ts_code'] for row in result['candidates']],
            [f'{600000 + index:06}.SH' for index in range(12, 2, -1)],
        )
        self.assertEqual(result['lookback'], 60)


if __name__ == '__main__':
    unittest.main()
