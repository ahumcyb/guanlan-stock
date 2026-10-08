import json
import unittest
from datetime import datetime,timedelta
from unittest.mock import Mock
from zoneinfo import ZoneInfo

from engine.datta import DattaError,DattaUnavailable

NOW=datetime(2026,10,8,14,30,5,tzinfo=ZoneInfo('Asia/Shanghai'))

def snapshot(**changes):
    value=dict(action='once',type='snapshot',symbol='600000.sh',code=0,name='浦发银行',market='sh',
               datetime=20261008143004,last_price=10200,prev_close=10000,open_price=10100,
               high_price=10300,low_price=10000,volume=100000,amount=1020000,
               recent_trades=[dict(trade_id=42,time=143004123,price=10200,volume=100,side='B')])
    value.update(changes);return value

def envelope(item):return json.dumps(dict(ts=int(NOW.timestamp()*1000),list=[item]))

class D20xDecodingTests(unittest.TestCase):
    def test_snapshot_uses_explicit_source_time_and_stock_units(self):
        from engine.d20x import decode_snapshot
        value=decode_snapshot(snapshot(),'600000.SH',NOW)
        self.assertEqual(value['quote']['close'],10.2)
        self.assertEqual(value['quote']['vol'],100000)
        self.assertEqual(value['quote']['amount'],1020000)
        self.assertEqual(value['date'],'20261008')
        self.assertEqual(value['quote']['trade_time'],'2026-10-08T14:30:04.123000+08:00')

    def test_snapshot_rejects_wrong_symbol_old_date_and_bad_units(self):
        from engine.d20x import decode_snapshot
        for changes in ({'symbol':'600001.sh'},{'datetime':20260930143004},
                        {'datetime':20261008},{'volume':1000},{'datetime':True}):
            with self.subTest(changes=changes),self.assertRaises(DattaError):
                decode_snapshot(snapshot(**changes),'600000.SH',NOW)

    def test_new_snapshot_receipt_cannot_make_old_trades_fresh(self):
        from engine.d20x import decode_snapshot
        old=[dict(trade_id=42,time=113000000,price=10200,volume=100,side='B')]
        with self.assertRaises(DattaError):decode_snapshot(snapshot(recent_trades=old),'600000.SH',NOW)
        with self.assertRaises(DattaError):decode_snapshot(snapshot(recent_trades=[]),'600000.SH',NOW)

    def test_same_millisecond_trades_keep_the_last_received_price(self):
        from engine.d20x import decode_snapshot
        rows=[dict(trade_id=41,time=143004123,price=10000,volume=100,side='B'),
              dict(trade_id=42,time=143004123,price=10200,volume=100,side='B')]
        self.assertEqual(decode_snapshot(snapshot(recent_trades=rows),'600000.SH',NOW)['quote']['close'],10.2)

    def test_malformed_optional_tape_cannot_discard_valid_quote_or_become_evidence(self):
        from engine.d20x import decode_snapshot
        trades=[dict(trade_id=31,time=143004123,price=10200,volume=100,side='')]*2
        value=decode_snapshot(snapshot(recent_trades=trades),'600000.SH',NOW)
        self.assertEqual(value['quote']['close'],10.2)
        self.assertEqual(value['recent_trades'],{})
        self.assertEqual(value['detail_status'],'unverified')

    def test_v95_hs300_units_are_not_the_stock_units(self):
        from engine.d20x import decode_snapshot
        value=snapshot(symbol='000300.sh',stock_type='1400',recent_trades=[],last_price=433867050,
                       prev_close=435761550,open_price=435492930,high_price=438356760,low_price=433550980,
                       volume=115579080,amount=280473388680,change_rate=.29)
        quote=decode_snapshot(value,'000300.SH',NOW)['quote']
        self.assertAlmostEqual(quote['close'],4338.6705)
        self.assertEqual(quote['vol'],11557908000)
        self.assertLess(quote['close']/quote['pre_close']-1,0)

    def test_d203_missing_direction_is_buy_only_for_matched_dated_event(self):
        from engine.d20x import decode_snapshot,trade_evidence
        snap=decode_snapshot(snapshot(),'600000.SH',NOW)
        item=dict(type='trade',symbol='SH600000',rows=[
            dict(seq=5,trade_no=42,time=143004123,price=10200,volume=100)])
        evidence=trade_evidence(item,'600000.SH',snap,NOW)
        self.assertEqual(evidence['matched_count'],1)
        self.assertEqual(evidence['sample_buy_amount'],1020)
        self.assertEqual(evidence['sample_sell_amount'],0)
        self.assertEqual(evidence['date'],'20261008')

    def test_transport_timestamp_never_fills_missing_d203_event_date(self):
        from engine.d20x import decode_snapshot,trade_evidence
        snap=decode_snapshot(snapshot(),'600000.SH',NOW)
        item=dict(type='trade',symbol='SH600000',rows=[
            dict(seq=5,trade_no=43,time=143004123,price=10200,volume=100)])
        evidence=trade_evidence(item,'600000.SH',snap,NOW)
        self.assertEqual(evidence['status'],'unverified_date')
        self.assertEqual(evidence['matched_count'],0)
        self.assertNotIn('sample_buy_amount',evidence)
        self.assertNotIn('date',evidence)

    def test_live_precision_and_seconds_format_require_exact_dated_trade_match(self):
        from engine.d20x import decode_snapshot,trade_evidence
        snap=decode_snapshot(snapshot(),'600000.SH',NOW)
        item=dict(type='trade',symbol='SH600000',precise=2,unit=100,rows=[
            dict(seq=5,trade_no=42,time=143004,price=1020,volume=100)])
        evidence=trade_evidence(item,'600000.SH',snap,NOW)
        self.assertEqual(evidence['sample_buy_amount'],1020)
        self.assertEqual(evidence['matched_count'],1)

    def test_omitted_price_is_never_forward_filled_and_returned_rows_are_capped(self):
        from engine.d20x import decode_snapshot,trade_evidence
        snap=decode_snapshot(snapshot(),'600000.SH',NOW)
        rows=[dict(trade_no=i,time=143004,volume=100) for i in range(1,40)]
        value=trade_evidence(dict(type='trade',symbol='SH600000',precise=2,rows=rows),'600000.SH',snap,NOW)
        self.assertEqual(value['sampled_count'],20)
        self.assertEqual(value['incomplete_count'],20)
        self.assertEqual(value['matched_count'],0)

    def test_conflicting_direction_or_duplicate_trade_is_rejected(self):
        from engine.d20x import decode_snapshot,trade_evidence
        snap=decode_snapshot(snapshot(),'600000.SH',NOW)
        row=dict(seq=5,trade_no=42,time=143004123,price=10200,volume=100,active_flag=1)
        with self.assertRaises(DattaError):trade_evidence(dict(type='trade',symbol='SH600000',rows=[row]),'600000.SH',snap,NOW)
        row.pop('active_flag')
        with self.assertRaises(DattaError):trade_evidence(dict(type='trade',symbol='SH600000',rows=[row,row]),'600000.SH',snap,NOW)

class FakeSocket:
    def __init__(self,frames):self.frames=iter(frames);self.sent=[];self.closed=False
    def __enter__(self):return self
    def __exit__(self,*_):self.closed=True
    def send(self,value):self.sent.append(json.loads(value))
    def recv(self,timeout):return next(self.frames)

class D20xTransportTests(unittest.TestCase):
    def test_once_snapshot_closes_connection_and_checks_lease_after_receive(self):
        from engine.d20x import D20xClient
        socket=FakeSocket([envelope(snapshot())]);lease=Mock()
        client=D20xClient(connector=lambda *a,**k:socket,session_check=lease,clock=lambda:NOW)
        self.assertEqual(client.quote('600000.SH')['close'],10.2)
        self.assertEqual(socket.sent,[dict(action='once',type='snapshot',symbol='600000.sh')])
        self.assertTrue(socket.closed)
        self.assertGreaterEqual(lease.call_count,3)

    def test_points_exhaustion_is_terminal_and_never_retried_as_d6(self):
        from engine.d20x import D20xClient
        socket=FakeSocket([envelope(dict(type='error',code=407))])
        client=D20xClient(connector=lambda *a,**k:socket,session_check=lambda:None,clock=lambda:NOW)
        with self.assertRaisesRegex(DattaUnavailable,'积分'):client.quote('600000.SH')
        self.assertEqual(len(socket.sent),1)
        self.assertTrue(socket.closed)

    def test_lost_lease_cannot_publish_a_received_snapshot(self):
        from engine.d20x import D20xClient
        socket=FakeSocket([envelope(snapshot())]);checks=iter([None,None,DattaUnavailable('lost lease')])
        def lease():
            error=next(checks)
            if error:raise error
        client=D20xClient(connector=lambda *a,**k:socket,session_check=lease,clock=lambda:NOW)
        with self.assertRaises(DattaUnavailable):client.quote('600000.SH')
        self.assertTrue(socket.closed)

    def test_d203_sample_always_unsubscribes(self):
        from engine.d20x import D20xClient
        item=dict(type='trade',symbol='SH600000',rows=[])
        socket=FakeSocket([envelope(item)])
        client=D20xClient(connector=lambda *a,**k:socket,session_check=lambda:None,clock=lambda:NOW)
        self.assertEqual(client.trade_sample('600000.SH')['rows'],[])
        self.assertEqual(socket.sent[-1],dict(type='trade',code='SH600000',enable=0))
        self.assertTrue(socket.closed)

    def test_subscription_ack_does_not_replace_actual_trade_rows(self):
        from engine.d20x import D20xClient
        ack=dict(type='trade',symbol='SH600000',action='subscribe',code=0)
        data=dict(type='trade',symbol='SH600000',action='push',rows=[])
        socket=FakeSocket([envelope(ack),envelope(data)])
        client=D20xClient(connector=lambda *a,**k:socket,session_check=lambda:None,clock=lambda:NOW)
        self.assertIn('rows',client.trade_sample('600000.SH'))

class D20xEnrichmentTests(unittest.TestCase):
    def test_dated_fragment_is_labelled_as_sample_without_changing_selection(self):
        from engine.d20x import decode_snapshot,enrich_candidates
        class Client:
            def trade_sample(self,code,budget=None):
                return dict(type='trade',symbol='SH600000',rows=[dict(seq=5,trade_no=42,time=143004123,price=10200,volume=100)])
            def snapshot(self,code,budget=None):return decode_snapshot(snapshot(),code,NOW)
        row=dict(ts_code='600000.SH',quote_at=NOW.timestamp(),price=10.2,checks=['原条件'],pending=[])
        report=dict(strategies={'overnight':[row],'golden':[]},generated_at=NOW.timestamp())
        enrich_candidates(report,Client(),clock=lambda:NOW)
        self.assertEqual(report['strategies']['overnight'],[row])
        self.assertEqual(row['price'],10.2)
        self.assertEqual(report['microstructure']['verified_count'],1)
        self.assertIn('样本',row['checks'][-1])
        self.assertIn('不代表全天',row['pending'][-1])

    def test_insufficient_freshness_headroom_avoids_paid_queries(self):
        from engine.d20x import enrich_candidates
        client=Mock()
        report=dict(strategies={'overnight':[dict(ts_code='600000.SH',quote_at=NOW.timestamp()-179,checks=[],pending=[])],'golden':[]})
        enrich_candidates(report,client,clock=lambda:NOW)
        client.trade_sample.assert_not_called()
        self.assertEqual(report['microstructure']['status'],'skipped')

if __name__=='__main__':unittest.main()
