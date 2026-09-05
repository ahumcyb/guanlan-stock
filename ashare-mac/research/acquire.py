"""Resume missing research constraints into a separate, verified local cache."""
import argparse
import fcntl
import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
from engine.data import atomic_json, validate, full_market_dates
from engine.provider import ProMax


def paged(client, api, params, page_size=1000):
    frames=[];seen=set();offset=0
    for _ in range(30):
        x=client._page(api, dict(params,limit=page_size,offset=offset))
        if x.empty:break
        if not {'ts_code','trade_date'}.issubset(x):raise ValueError('Response lacks keys')
        keys=set(x[['ts_code','trade_date']].itertuples(index=False,name=None))
        if keys & seen:raise ValueError('Pagination overlaps; cannot establish completeness')
        seen.update(keys);frames.append(x);offset+=len(x)
        if len(x)<page_size:break
    else:raise ValueError('Research pagination exceeded bounded budget')
    return pd.concat(frames,ignore_index=True).drop_duplicates() if frames else pd.DataFrame()


def check_limits(x, date, codes):
    x=validate(x.drop_duplicates(),'stk_limit')
    if set(x.trade_date)!={date} or len(codes & set(x.ts_code)) < .99*len(codes):
        raise ValueError('Limit date or daily universe coverage failed')
    return x


def check_status(x, dates, minimum=20):
    if not {'ts_code','trade_date'}.issubset(x) or x.empty:raise ValueError('Missing historical ST status')
    x=x.copy();x['trade_date']=x.trade_date.astype(str)
    if x[['ts_code','trade_date']].isna().any().any() or not x.ts_code.str.fullmatch(r'\d{6}\.(SH|SZ|BJ)').all():
        raise ValueError('Invalid ST keys')
    if x.duplicated(['ts_code','trade_date']).any():raise ValueError('Ambiguous ST status')
    counts=x.groupby('trade_date').size()
    if not set(dates).issubset(counts.index) or (counts.reindex(dates)<minimum).any():
        raise ValueError('Historical ST dates missing or suspiciously small')
    return x.loc[x.trade_date.isin(dates)].reset_index(drop=True)


def status_span(client, dates, cap=1000):
    params={'trade_date':dates[0]} if len(dates)==1 else {'start_date':dates[0],'end_date':dates[-1]}
    x=client._page('stock_st',dict(params,limit=cap))
    # Range caps and inconsistent pagination must not silently truncate a day's ST list.
    # A saturated response is split in time, never accepted as complete.
    if len(x)>=cap:
        if len(dates)==1:raise ValueError('ST day exceeds verified response capacity')
        middle=len(dates)//2
        return pd.concat([status_span(client,dates[:middle],cap),status_span(client,dates[middle:],cap)],ignore_index=True)
    return check_status(x,dates)


def save(path, table):
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix('.pending.parquet')
    table.to_parquet(temporary,index=False)
    pd.testing.assert_frame_equal(table.reset_index(drop=True),pd.read_parquet(temporary))
    os.replace(temporary,path)


def acquire(root, cache):
    cache.mkdir(parents=True,exist_ok=True)
    protocol=json.loads(Path(__file__).with_name('protocol.json').read_text())
    manifest=json.loads((root/'manifest.json').read_text())
    if manifest['revision']!=protocol['data_revision']:raise ValueError('Unexpected research source revision')
    daily=pd.read_parquet(root/'raw/daily.parquet',columns=['trade_date','ts_code'])
    dates=[d for d in full_market_dates(daily.groupby('trade_date').size().sort_index())
           if protocol['train'][0]<=d<=protocol['holdout'][1]]
    basic=daily.loc[daily.ts_code.str.fullmatch(r'(00\d{4}\.SZ|60\d{4}\.SH)')]
    codes={d:set(g.ts_code) for d,g in basic.groupby('trade_date') if d in dates}
    existing=pd.read_parquet(root/'raw/stk_limit.parquet')
    by_date={d:g for d,g in existing.groupby('trade_date')}
    months={m:[d for d in dates if d.startswith(m)] for m in sorted({d[:6] for d in dates})}
    jobs=[]
    for date in dates:
        target=cache/'limits'/(date+'.parquet')
        if target.exists():check_limits(pd.read_parquet(target),date,codes[date])
        elif date in by_date:save(target,check_limits(by_date[date],date,codes[date]))
        else:jobs.append(('limits',date))
    for month,days in months.items():
        target=cache/'status'/(month+'.parquet')
        if target.exists():check_status(pd.read_parquet(target),days)
        else:jobs.append(('status',month))
    # Short ST batches share the same three-worker request budget as prices.
    jobs.sort(key=lambda j:(j[0]!='status',j[1]))
    print(f'Constraint cache: {len(dates)} sessions; {len(jobs)} missing date/month partitions',flush=True)

    def fetch(job):
        kind,key=job;c=ProMax();target=cache/kind/(key+'.parquet')
        if kind=='limits':
            table=check_limits(paged(c,'stk_limit',{'trade_date':key},page_size=7800),key,codes[key])
        else:
            days=months[key]
            table=check_status(pd.concat([status_span(c,days[i:i+4]) for i in range(0,len(days),4)],ignore_index=True),days)
        save(target,table)
        return kind,key,len(table)

    failures=[];completed=0
    with ThreadPoolExecutor(max_workers=3) as pool:
        pending={pool.submit(fetch,job):job for job in jobs}
        for future in as_completed(pending):
            try:
                result=future.result();completed+=1
                print(f'{completed}/{len(jobs)} verified {result}',flush=True)
            except Exception as e:
                kind,key=pending[future]
                error=str(e) if isinstance(e,ValueError) else type(e).__name__
                failures.append({'kind':kind,'period':key,'error':error})
                print(f'Incomplete {kind} {key}: {error}; retained completed partitions',flush=True)
    files=[]
    for p in sorted(cache.glob('*/*.parquet')):
        files.append({'path':str(p.relative_to(cache)),'bytes':p.stat().st_size,
                      'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'rows':len(pd.read_parquet(p))})
    result={'source_revision':manifest['revision'],'dates':dates,'files':files,'failures':failures,
            'complete':not failures and len(files)==len(dates)+len(months)}
    atomic_json(cache/'manifest.json',result)
    print('Research constraints complete:',result['complete'],flush=True)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--cache',type=Path,required=True);args=parser.parse_args()
    args.cache.mkdir(parents=True,exist_ok=True)
    with (args.cache/'.lock').open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        result=acquire(args.root.resolve(),args.cache.resolve())
    raise SystemExit(0 if result['complete'] else 1)
