import json
import unittest
from unittest.mock import patch
import pandas as pd
from engine.intraday_runner import IntradayProvider, canonical_snapshots, incomplete_days, check_day, checked_shares
from mobile_server.notifications import send_bark, deepseek_review
from engine.intraday import local_now


class Response:
    def __init__(self, value):self.value=value
    def __enter__(self):return self
    def __exit__(self, *args):pass
    def read(self, limit):return json.dumps(self.value).encode()[:limit]


class RealtimeIntegrationTests(unittest.TestCase):
    def test_bark_key_only_in_body_and_timeout_is_not_replayed(self):
        event=dict(title='观澜测试',body='测试内容',url='guanlan://alerts/test')
        with patch('mobile_server.notifications.build_opener') as factory:
            factory.return_value.open.return_value=Response({'code':200})
            self.assertEqual(send_bark('privateDeviceKey123',event),'accepted')
            request=factory.return_value.open.call_args.args[0]
            self.assertEqual(request.full_url,'https://api.day.app/push')
            self.assertEqual(json.loads(request.data)['device_key'],'privateDeviceKey123')
            factory.return_value.open.side_effect=TimeoutError()
            self.assertEqual(send_bark('privateDeviceKey123',event),'unknown')

    def test_ai_cannot_add_codes_or_truncated_json_to_rules(self):
        report=dict(date='20260904',strategies={'overnight':[dict(ts_code='600000.SH',name='浦发银行',change=4,checks=['量能'],pending=['公告'])],'golden':[]})
        for content, finish, expected in [
            ({'summary':'量能满足阈值，公告仍需核查','risks':['隔夜跳空']},'stop','ready'),
            ({'summary':'改买别的','risks':[],'stocks':['600001.SH']},'stop','unavailable'),
            ({'summary':'未完成','risks':[]},'length','unavailable')]:
            with patch('mobile_server.notifications.build_opener') as factory:
                factory.return_value.open.return_value=Response({'choices':[{'finish_reason':finish,'message':{'content':json.dumps(content)}}]})
                value=deepseek_review('privateAIKey123','deepseek-v4-flash',report)
                self.assertEqual(value['status'],expected)
                request=factory.return_value.open.call_args.args[0]
                self.assertEqual(request.full_url,'https://api.deepseek.com/chat/completions')
                self.assertNotIn(b'privateAIKey123',request.data)
                self.assertEqual(report['strategies']['overnight'][0]['ts_code'],'600000.SH')

    def test_promax_transient_response_has_one_bounded_retry(self):
        client=object.__new__(IntradayProvider);client._secret='privateProviderKey123'
        values=[Response({'code':-1000,'count':0,'data':None}),Response({'code':0,'count':1,'data':{'fields':['ts_code'],'items':[['600000.SH']]}})]
        with patch('engine.intraday_runner.build_opener') as factory, patch('engine.intraday_runner.time.sleep'):
            factory.return_value.open.side_effect=values
            self.assertEqual(len(client.get('rt_k',ts_code='600000.SH')),1)
            self.assertEqual(factory.return_value.open.call_count,2)
            request=factory.return_value.open.call_args.args[0]
            self.assertNotIn(client._secret,request.full_url)

    def test_unrequested_primary_rows_are_rejected_before_using_fallback(self):
        now=local_now().replace(year=2026,month=9,day=7,hour=14,minute=45,second=0,microsecond=0)
        sample=dict(name='测试',pre_close=10,open=10,high=10.5,low=10,close=10.4,vol=100,amount=1040,trade_time=now.isoformat())
        class Fake(IntradayProvider):
            def __init__(self):pass
            def get(self, api, **args):
                return pd.DataFrame([dict(sample,ts_code=c) for c in ['600000.SH','600001.SH']])
        with patch('engine.intraday_runner.local_now',return_value=now), \
             patch('engine.intraday_runner.sina_quotes',return_value=[dict(sample,ts_code='600000.SH')]) as fallback:
            rows=Fake().quotes(['600000.SH'])
        self.assertEqual([r['ts_code'] for r in rows],['600000.SH'])
        fallback.assert_called_once_with(['600000.SH'])

    def test_duplicate_transport_timestamp_cannot_refresh_an_old_quote(self):
        row=dict(ts_code='600000.SH',name='测试',pre_close=10,open=10,high=10.5,low=10,close=10.4,vol=100,amount=1040,trade_time='20260904')
        frame=pd.DataFrame([dict(row,updated_at='2026-09-04T14:45:00'),dict(row,updated_at='2026-09-04T14:50:00')])
        clean, conflicts=canonical_snapshots(frame)
        self.assertEqual(len(clean),1);self.assertEqual(conflicts,0)
        self.assertEqual(clean.iloc[0].updated_at,'2026-09-04T14:45:00')
        frame.loc[1,'vol']=101
        clean, conflicts=canonical_snapshots(frame)
        self.assertEqual(len(clean),0);self.assertEqual(conflicts,1)

    def test_truncated_previous_day_is_scheduled_for_repair(self):
        counts=pd.Series([5500,5500,4500],index=['20260901','20260902','20260903'])
        self.assertEqual(incomplete_days(counts,counts.index.tolist(),'20260903'),['20260903'])

    def test_truncated_download_cannot_become_a_complete_history_partition(self):
        counts=pd.Series([5500,5500],index=['20260901','20260902'])
        sample=dict(trade_date='20260903',open=10,high=11,low=9,close=10,pre_close=10,vol=100,amount=100)
        frame=pd.DataFrame([dict(sample,ts_code=f'{i:06}.SZ') for i in range(4500)])
        with self.assertRaises(ValueError):check_day(frame,'20260903',counts)

    def test_share_coverage_uses_the_actual_previous_universe(self):
        codes={f'{i:06}.SZ' for i in range(5500)}
        frame=pd.DataFrame(dict(ts_code=sorted(codes)[:4500],trade_date='20260903',float_share=100))
        with self.assertRaises(ValueError):checked_shares(frame,'20260903',codes)
        frame=pd.DataFrame(dict(ts_code=sorted(codes),trade_date='20260903',float_share=100))
        self.assertEqual(len(checked_shares(frame,'20260903',codes)),5500)


if __name__=='__main__':unittest.main()
