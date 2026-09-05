"""Next-open signal event study; deliberately not a capital-weighted portfolio."""
from collections import Counter
import math
import numpy as np
import pandas as pd
from .strategy import select_day


def available(quote):
    return quote is not None and all(
        isinstance(quote.get(k), (float, int)) and math.isfinite(quote[k]) and quote[k] > 0
        for k in ['open', 'close', 'pre_close', 'vol', 'adj_factor', 'up_limit', 'down_limit'])


def evaluate_event(code, date, horizon, dates, quotes, cost=.003):
    if horizon not in (1, 3, 5):
        raise ValueError('持有期必须为 1、3 或 5 个交易日')
    result = dict(code=code, signal_date=date, horizon=horizon, status='pending')
    i = dates.index(date)
    if i+1 >= len(dates):
        return result
    signal = quotes.get((date, code))
    if not available(signal):
        return dict(result, status='missing_signal')
    entry_date = dates[i+1]
    entry = quotes.get((entry_date, code))
    if not available(entry):
        return dict(result, status='missing_entry')
    if entry['open'] >= entry['up_limit']-.001:
        return dict(result, status='limit_up')
    if entry['open']/entry['pre_close'] > 1.03:
        return dict(result, status='gap')
    result['entry_date'] = entry_date
    target = i+1+horizon
    if target >= len(dates):
        return result
    for j in range(target, min(target+6, len(dates))):
        exit_quote = quotes.get((dates[j], code))
        if not available(exit_quote) or exit_quote['open'] <= exit_quote['down_limit']+.001:
            continue
        gross = (exit_quote['open']*exit_quote['adj_factor'])/(entry['open']*entry['adj_factor'])-1
        return dict(result, status='settled', exit_date=dates[j], delay=j-target,
                    gross_return=float(gross), net_return=float(gross-cost),
                    stress_return=float(gross-2*cost))
    # Do not silently discard potentially locked losing positions.
    return dict(result, status='unresolved')


def summarize(events):
    settled = [e for e in events if e['status'] == 'settled']
    values = np.array([e['net_return'] for e in settled])
    statuses = dict(Counter(e['status'] for e in events))
    if not len(values):
        return dict(count=0, total=len(events), mean=None, median=None, win_rate=None,
                    stress_mean=None, worst=None, p10=None, statuses=statuses)
    return dict(count=len(values), total=len(events), mean=float(values.mean()),
                median=float(np.median(values)), win_rate=float((values>0).mean()),
                stress_mean=float(np.mean([e['stress_return'] for e in settled])),
                worst=float(values.min()), p10=float(np.quantile(values,.1)), statuses=statuses)


def study(signals: pd.DataFrame, factors: pd.DataFrame, limits: pd.DataFrame, dates):
    counts = limits.groupby('trade_date').size()
    covered = counts[counts >= 4000].index.tolist()
    if not covered:
        return dict(start='', end='', horizons=[], monthly=[], events=[], benchmark_label='流动性前十参照')
    start = min(covered)
    subset = signals[signals.trade_date >= start]
    columns = ['ts_code', 'trade_date', 'open', 'high', 'low', 'close', 'pre_close', 'vol']
    merged = subset[columns].merge(factors, on=['ts_code','trade_date'], how='left', validate='one_to_one')
    merged = merged.merge(limits, on=['ts_code','trade_date'], how='left', validate='one_to_one')
    quotes = {(r['trade_date'],r['ts_code']): r for r in merged.to_dict('records')}
    signals_by_date, reference_by_date = {}, {}
    for date, day in subset.groupby('trade_date', sort=True):
        chosen = select_day(day)
        signals_by_date[date] = chosen.ts_code.tolist()
        # Baseline selected with D-day information on the same signal dates.
        reference = day[day.eligible].sort_values(['amount20','ts_code'], ascending=[False,True]).copy()
        reference['industry'] = reference.industry.fillna('未分类')
        reference = reference[reference.groupby('industry').cumcount() < 2].head(10)
        reference_by_date[date] = reference.ts_code.tolist()
    events, horizons = [], []
    for h in (1,3,5):
        current, baseline = [], []
        for date, codes in signals_by_date.items():
            for code in codes:
                current.append(evaluate_event(code,date,h,dates,quotes))
            if codes:
                for code in reference_by_date[date]:
                    baseline.append(evaluate_event(code,date,h,dates,quotes))
        summary, benchmark = summarize(current), summarize(baseline)
        horizons.append(dict(horizon=h, **summary, benchmark=benchmark))
        events.extend(current)
    monthly = []
    months = sorted({e['signal_date'][:6] for e in events})
    for month in months:
        monthly.append(dict(month=month, **summarize([e for e in events if e['horizon']==3 and e['signal_date'].startswith(month)])))
    return dict(start=start, end=dates[-1], horizons=horizons, monthly=monthly, events=events,
                benchmark_label='同信号日基础池成交额前十 · 每行业最多两只')
