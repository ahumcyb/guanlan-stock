import unittest
from unittest.mock import patch
from engine.sina_quotes import parse_quotes, fetch_quotes
from engine.intraday import normalize_quote, local_now


def snapshot(code='sh600000',date='2026-09-07',clock='14:44:23'):
    fields=['测试股份','10','10','10.4','10.5','9.9','10.39','10.4','1000','10400']+['0']*20+[date,clock,'00']
    return ('var hq_str_'+code+'="'+','.join(fields)+'";\n').encode('gb18030')


class Response:
    def __init__(self,body):self.body=body
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def read(self,limit):return self.body[:limit]


class SinaQuoteTests(unittest.TestCase):
    def test_source_date_and_time_are_preserved_and_not_refreshed(self):
        rows=parse_quotes(snapshot(),['600000.SH'])
        self.assertEqual(rows[0]['trade_time'],'2026-09-07 14:44:23')
        self.assertEqual(rows[0]['quote_source'],'sina')
        now=local_now().replace(year=2026,month=9,day=7,hour=14,minute=45,second=0,microsecond=0)
        self.assertEqual(normalize_quote(rows[0],now)['time_basis'],'trade_time')
        with self.assertRaises(ValueError):normalize_quote(rows[0],now.replace(hour=21))

    def test_missing_source_time_unrequested_and_duplicate_symbols_are_rejected(self):
        for body in [snapshot(clock=''),snapshot('sh600001'),snapshot()+snapshot(),b'<html>blocked</html>']:
            with self.subTest(body=body),self.assertRaises(ValueError):parse_quotes(body,['600000.SH'])

    def test_https_fixed_source_request_cannot_carry_promax_credentials(self):
        with patch('engine.sina_quotes.build_opener') as factory:
            factory.return_value.open.return_value=Response(snapshot())
            self.assertEqual(len(fetch_quotes(['600000.SH'])),1)
            request=factory.return_value.open.call_args.args[0]
            self.assertEqual(request.full_url,'https://hq.sinajs.cn/list=sh600000')
            self.assertEqual({name.lower() for name,_ in request.header_items()},{'referer','user-agent'})
            self.assertLessEqual(factory.return_value.open.call_args.kwargs['timeout'],6)

    def test_request_limit_and_code_validation_precede_network(self):
        with patch('engine.sina_quotes.build_opener') as factory:
            for codes in [['600000.SH,other'],['600000.SH']*2,[f'{n:06}.SZ' for n in range(201)]]:
                with self.assertRaises(ValueError):fetch_quotes(codes)
            factory.assert_not_called()
