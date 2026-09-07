import json
import unittest
from urllib.error import HTTPError
from unittest.mock import patch
from tests.test_realtime_integrations import Response
from mobile_server.notifications import deepseek_daily_review


class DailyAITests(unittest.TestCase):
    def test_strict_structured_reply_and_secrets_never_enter_prompt(self):
        key='test-key-not-production'
        content=dict(headline='收盘复盘',market_view='涨跌分化',sector_view='行业表现分化',
                     strategy_view='候选仍需观察',watch_next='观察量价确认',risks=['未核验新闻'])
        evidence={'date':'20260904','market':{'stock_count':5000},'strategies':[],
                  'sectors_strong':[],'sectors_weak':[],'warnings':[],'universe_label':'沪深 A 股'}
        with patch('mobile_server.notifications.build_opener') as factory:
            factory.return_value.open.return_value=Response({'choices':[{'finish_reason':'stop','message':{'content':json.dumps(content)}}]})
            result=deepseek_daily_review(key,'deepseek-v4-flash',evidence)
            self.assertEqual(result['status'],'ready')
            request=factory.return_value.open.call_args.args[0]
            self.assertEqual(request.full_url,'https://api.deepseek.com/chat/completions')
            self.assertNotIn(key.encode(),request.data)
            payload=json.loads(request.data)
            self.assertEqual(payload['thinking'],{'type':'disabled'})
            self.assertLessEqual(payload['max_tokens'],2000)

    def test_truncation_wrong_schema_and_echoed_key_are_rejected(self):
        key='test-key-not-production'
        for content,finish in [({'headline':'partial'},'length'),({'execute':'shell'},'stop'),({'headline':key},'stop')]:
            with patch('mobile_server.notifications.build_opener') as factory:
                factory.return_value.open.return_value=Response({'choices':[{'finish_reason':finish,'message':{'content':json.dumps(content)}}]})
                result=deepseek_daily_review(key,'deepseek-v4-flash',{})
                self.assertEqual(result['status'],'unavailable')
                self.assertNotIn(key,json.dumps(result))

    def test_auth_or_balance_failures_are_actionable_without_raw_response(self):
        for code,label in [(401,'authentication'),(402,'balance'),(429,'rate_limited')]:
            with patch('mobile_server.notifications.build_opener') as factory:
                factory.return_value.open.side_effect=HTTPError('https://api.deepseek.com/chat/completions',code,'private response',{},None)
                result=deepseek_daily_review('test-key-not-production','deepseek-v4-flash',{})
                self.assertEqual(result['error_code'],label)
                self.assertNotIn('private response',json.dumps(result))

    def test_unicode_escaped_key_echo_is_also_rejected_after_parsing(self):
        key='test-key-not-production'
        encoded=''.join('\\u'+format(ord(char),'04x') for char in key)
        content='{"headline":"'+encoded+'","market_view":"x","sector_view":"x","strategy_view":"x","watch_next":"x","risks":[]}'
        with patch('mobile_server.notifications.build_opener') as factory:
            factory.return_value.open.return_value=Response({'choices':[{'finish_reason':'stop','message':{'content':content}}]})
            result=deepseek_daily_review(key,'deepseek-v4-flash',{})
            self.assertEqual(result['status'],'unavailable')
            self.assertNotIn(key,json.dumps(result))
