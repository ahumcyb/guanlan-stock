import json
import unittest
from urllib.error import HTTPError
from unittest.mock import patch
from tests.test_realtime_integrations import Response
from mobile_server.notifications import deepseek_daily_review


class DailyAITests(unittest.TestCase):
    def test_verified_differences_are_sent_for_explanation_without_today_pick_returns(self):
        content=dict(headline='变化',market_view='成交额变化+5%。',sector_view='行业均值榜有变化。',strategy_view='昨日精选仍需观察。',watch_next='若条件再次满足，再观察。',risks=[])
        evidence={'market_changes':{'previous_date':'20260904','turnover_change_pct':5.},
                  'selection_changes':[{'id':'leaders','added':[],'retained':[{'ts_code':'000001.SZ','name':'例子'}],'removed':[]}],
                  'strategies':[{'id':'leaders','name':'趋势','shortlist_count':1,'picks':[{'change':99.}]}]}
        with patch('mobile_server.notifications.build_opener') as factory:
            factory.return_value.open.return_value=Response({'choices':[{'finish_reason':'stop','message':{'content':json.dumps(content)}}]})
            self.assertEqual(deepseek_daily_review('test-key-not-production','deepseek-v4-flash',evidence)['status'],'ready')
            request=factory.return_value.open.call_args[0][0]
            payload=json.loads(request.data);data=json.loads(payload['messages'][1]['content'])
            self.assertEqual(data['market_changes']['turnover_change_pct'],5.)
            self.assertEqual(data['selection_changes'][0]['retained'][0]['ts_code'],'000001.SZ')
            self.assertTrue(data['available_data']['historical_turnover'])
            self.assertNotIn('picks',data['current_shortlists'][0])

    def test_single_day_turnover_does_not_support_flow_valuation_or_history_claims(self):
        content=dict(headline='收盘复盘',market_view='涨跌分化',sector_view='行业表现分化',
                     strategy_view='候选仍需观察',watch_next='若下一交易日上涨家数增加，再观察行情改善是否持续。',risks=[])
        for field,claim in [('market_view','资金从高估值成长流向低估值防守板块。'),
                            ('sector_view','半导体成交额较大，资金流出明显。'),
                            ('market_view','成交额维持在两万亿以上。'),
                            ('sector_view','饲料行业放量上涨。'),
                            ('watch_next','观察指数能否站上关键位。'),
                            ('watch_next','沪指将站上关键点位。'),
                            ('watch_next','明日必将放量连续上涨。'),
                            ('watch_next','若干指标分化，明日必将放量连续上涨。'),
                            ('market_view','北向资金今日净买入明显。'),
                            ('sector_view','成长股估值较高。'),
                            ('market_view','上证收于3500点。')]:
            with self.subTest(claim=claim),patch('mobile_server.notifications.build_opener') as factory:
                result_content=dict(content,**{field:claim})
                factory.return_value.open.return_value=Response({'choices':[{'finish_reason':'stop','message':{'content':json.dumps(result_content)}}]})
                result=deepseek_daily_review('test-key-not-production','deepseek-v4-flash',{})
                self.assertEqual(result['status'],'unavailable')
                self.assertEqual(result['error_code'],'unsupported_claim')

    def test_strategy_name_and_conditional_future_volume_observation_are_allowed(self):
        content=dict(headline='收盘分化',market_view='下跌家数多于上涨家数。',sector_view='行业表现分化。',
                     strategy_view='缩量回踩转强有十只候选。缩量回踩和黄金坑候选上涨。',
                     watch_next='若下一交易日成交额放大且上涨家数增加，再观察回暖能否持续。',risks=['未提供指数、估值或资金流数据。','单日结果不能确认后续延续性。'])
        evidence={'strategies':[{'name':'缩量回踩转强','picks':[]}]}
        with patch('mobile_server.notifications.build_opener') as factory:
            factory.return_value.open.return_value=Response({'choices':[{'finish_reason':'stop','message':{'content':json.dumps(content)}}]})
            self.assertEqual(deepseek_daily_review('test-key-not-production','deepseek-v4-flash',evidence)['status'],'ready')

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

    def test_only_previous_selection_performance_can_supply_strategy_returns(self):
        evidence={'market':{'breadth':.4574,'advancers':2249,'decliners':2773},'strategies':[{'name':'60 日风险调整动量','picks':[
            {'change':-1.47},{'change':.086},{'change':.373},{'change':-1.35},{'change':-1.17}]}]}
        evidence['performance']={'signal_date':'20260904','evaluation_date':'20260907','status':'available',
            'strategies':[{'id':'momentum_60','up_count':2,'down_count':3,'flat_count':0,'mean_return_pct':-1.2}]}
        original=json.dumps(evidence,sort_keys=True)
        content=dict(headline='收盘分化',market_view='涨跌分化',sector_view='行业分化',strategy_view='候选表现分化',watch_next='观察确认',risks=[])
        with patch('mobile_server.notifications.build_opener') as factory:
            factory.return_value.open.return_value=Response({'choices':[{'finish_reason':'stop','message':{'content':json.dumps(content)}}]})
            self.assertEqual(deepseek_daily_review('test-key-not-production','deepseek-v4-pro',evidence)['status'],'ready')
            payload=json.loads(factory.return_value.open.call_args.args[0].data)
            data=json.loads(payload['messages'][1]['content'])
            self.assertNotIn('strategies',data)
            self.assertNotIn('picks',data['current_shortlists'][0])
            self.assertEqual(data['performance'],evidence['performance'])
            self.assertNotIn('breadth',data['market'])
            self.assertEqual(data['market']['strategy_pool_above_ma20_pct'],45.74)
            self.assertEqual(data['market']['advancer_decliner_ratio'],.811)
            self.assertEqual(json.dumps(evidence,sort_keys=True),original)

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
