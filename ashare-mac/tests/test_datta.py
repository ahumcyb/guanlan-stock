import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from engine.datta import DattaClient, DattaError, decode_quote, decode_bars, validate_base_url
from engine.intraday import normalize_quote

NOW = datetime(2026, 9, 8, 14, 30, tzinfo=ZoneInfo('Asia/Shanghai'))


def quote_payload(code='600000', market='sh', **changes):
    row = dict(prodCode=code, hqTypeCode=market, prodName='浦发银行', lastPx=9280,
               preClosePx=9230, openPrice=9210, highPx=9340, lowPx=9210,
               businessAmount=40377931, businessBalance=374763157,
               marketDate=20260908, dataTimestamp=int(NOW.timestamp()), circulationAmount=33305838300)
    row.update(changes)
    return dict(code=0, data=row, timestamp=int(NOW.timestamp()*1000))


def bars_payload(**changes):
    row = dict(TradingDay=int(NOW.replace(hour=0, minute=0).timestamp()),
               Time=int(NOW.timestamp()), Open=9.21, High=9.34, Low=9.21, Close=9.28,
               Volume=40377931, Amount=374763157, PreClose=9.23)
    row.update(changes)
    return dict(Code=0, Msg='Success', KlineData=[row])


class DattaTests(unittest.TestCase):
    def test_loopback_endpoint_never_accepts_credentials_remote_hosts_or_paths(self):
        self.assertEqual(validate_base_url('http://127.0.0.1:8080/'), 'http://127.0.0.1:8080')
        for url in ['http://user:pass@127.0.0.1:8080', 'http://example.com:8080',
                    'http://169.254.169.254', 'http://127.0.0.1:8080/other',
                    'http://127.0.0.1:8080?token=private', 'file:///tmp/data']:
            with self.subTest(url=url), self.assertRaises(DattaError):
                validate_base_url(url)

    def test_verified_d6_units_and_stock_source_time(self):
        row = decode_quote(quote_payload(), '600000.SH')
        quote = normalize_quote(row, NOW)
        self.assertEqual(quote['close'], 9.28)
        self.assertEqual(quote['vol'], 40377931)
        self.assertEqual(quote['amount'], 374763157)
        self.assertEqual(quote['quote_at'], NOW.timestamp())
        self.assertEqual(quote['time_basis'], 'provider_updated_at')

    def test_fresh_envelope_time_cannot_relabel_old_or_missing_stock_time(self):
        stale = quote_payload(dataTimestamp=int(NOW.timestamp())-181)
        with self.assertRaises(ValueError):
            normalize_quote(decode_quote(stale, '600000.SH'), NOW)
        for field,value in [('dataTimestamp',None),('marketDate',20260907)]:
            with self.subTest(field=field), self.assertRaises(DattaError):
                decode_quote(quote_payload(**{field:value}), '600000.SH')

    def test_observed_thousandth_truncation_returns_the_equity_cent_price(self):
        row=decode_quote(quote_payload(lastPx=9289),'600000.SH')
        self.assertEqual(row['close'],9.29)

    def test_wrong_symbol_business_error_and_invalid_units_are_rejected(self):
        for payload in [quote_payload(code='600001'),quote_payload(market='sz'),
                        quote_payload(lastPx=928),quote_payload(businessAmount=float('nan')),
                        dict(code=-1,data=quote_payload()['data'],errorMessage='private token')]:
            with self.subTest(payload=payload), self.assertRaises(DattaError) as raised:
                decode_quote(payload, '600000.SH')
            self.assertNotIn('private token',str(raised.exception))

    def test_daily_and_minute_conversion_keep_distinct_volume_units(self):
        daily = decode_bars(bars_payload(), '600000.SH', 'DAY', '20260908', '20260908')
        self.assertEqual(daily[0]['trade_date'],'20260908')
        self.assertEqual(daily[0]['vol'],403779.31)
        self.assertEqual(daily[0]['amount'],374763.157)
        minute = decode_bars(bars_payload(), '600000.SH', 'MIN1', '20260908', '20260908')
        self.assertEqual(minute[0]['vol'],40377931)
        self.assertEqual(minute[0]['amount'],374763157)
        self.assertIn('14:30:00',minute[0]['time'])

    def test_history_never_makes_a_wrong_date_or_duplicate_bar_look_complete(self):
        duplicate=bars_payload();duplicate['KlineData']*=2
        for data in [bars_payload(TradingDay=1788710400),duplicate,bars_payload(High=9.0),
                     dict(Code=-1,Msg='not authorized',KlineData=[])]:
            with self.subTest(data=data),self.assertRaises(DattaError):
                decode_bars(data,'600000.SH','MIN1','20260908','20260908')
        self.assertEqual(decode_bars(dict(Code=0,KlineData=[]),'600000.SH','DAY','20260908','20260908'),[])

    def test_beijing_daily_codes_and_query_dates_are_preserved(self):
        calls=[]
        def transport(path,params):
            calls.append((path,params));return bars_payload()
        client=DattaClient(transport=transport)
        rows=client.history('920000.BJ','DAY','20260908','20260908')
        self.assertEqual(rows[0]['ts_code'],'920000.BJ')
        self.assertEqual(calls[0][1]['market'],'BJ')
        self.assertEqual(calls[0][1]['period'],'DAY')
        self.assertEqual(calls[0][1]['startTime'],int(NOW.replace(hour=0,minute=0).timestamp()))
        self.assertEqual(calls[0][1]['limit']%50,0)

    def test_batch_keeps_valid_rows_and_records_unavailable_codes_without_payloads(self):
        def transport(path,params):
            code=params['symbol'][2:]
            return quote_payload(code=code) if code!='600001' else dict(code=-1,errorMessage='private value')
        client=DattaClient(transport=transport,workers=2)
        rows=client.quotes(['600000.SH','600001.SH','600002.SH'])
        self.assertCountEqual([r['ts_code'] for r in rows],['600000.SH','600002.SH'])
        self.assertEqual(client.diagnostics['unavailable'],1)
        self.assertNotIn('private value',str(client.diagnostics))
