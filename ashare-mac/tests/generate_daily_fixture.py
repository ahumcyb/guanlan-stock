"""Offline native-client fixture built through the actual daily workflow."""
import argparse,json,tempfile
from pathlib import Path
from tests.test_daily_facts import published_fixture
from tests.test_close_proof import NOW,DATE
from mobile_server.daily import DailyStore

def create(output):
    with tempfile.TemporaryDirectory() as folder:
        root,market=published_fixture(folder)
        import pandas as pd
        from tests.test_daily_realtime_performance import run
        from mobile_server.realtime_history import RealtimeArchive
        raw=market/'current/raw';current=pd.read_parquet(raw/'daily.parquet');code=current.iloc[1].ts_code
        prior=current.iloc[[1]].copy();prior['trade_date']='20260903';prior['close']=8.
        pd.concat([prior,current],ignore_index=True).to_parquet(raw/'daily.parquet',index=False)
        factors=pd.read_parquet(raw/'adj_factor.parquet');previous=factors.iloc[[1]].copy();previous['trade_date']='20260903'
        pd.concat([previous,factors],ignore_index=True).to_parquet(raw/'adj_factor.parquet',index=False)
        pd.DataFrame(dict(exchange=['SSE','SSE'],cal_date=['20260903',DATE],is_open=[1,1])).to_parquet(raw/'trade_cal.parquet',index=False)
        archive=root/'jobs/realtime';archive.mkdir(parents=True)
        realtime=run(date='20260903');realtime['strategies']['overnight'][0].update(ts_code=code,price=9.)
        RealtimeArchive(archive).collect(dict(runs=[run('1430',date='20260903'),realtime],events=[]))
        store=DailyStore(root,lambda:NOW.timestamp())
        store.realtime.calendar([DATE,'20260907'])
        store.configure({'enabled':True,'deepseek_key':'fixture-key-not-production'})
        def analyze(key,model,evidence):
            return dict(status='ready',model=model,headline='收盘复盘 · 原生测试',market_view='量价样本已核验。',
                        sector_view='行业均值仅供观察。',strategy_view='四套研究条件保持一致。',watch_next='关注后续量价确认。',risks=['测试样本，不用于选股。'])
        store.tick(market/'current',analyze=analyze)
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps(store.public(),ensure_ascii=False))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    create(parser.parse_args().output)
