"""Freeze implementation, choose on development dates, then unlock one candidate."""
import argparse
import json
from pathlib import Path
import numpy as np
import pandas as pd
from engine.data import atomic_json
from .prepare import sha
from .signals import NAMES
from .simulator import simulate, cash_profit_factor

APP=Path(__file__).resolve().parents[1]
SOURCES=['research/signals.py','research/simulator.py','research/prepare.py','research/experiment.py','research/acquire.py',
         'research/protocol.json','research/PLAN.md','engine/strategy.py','engine/golden_pit.py','engine/data.py','engine/provider.py']


def verify_hashes(root, hashes):
    for name,digest in hashes.items():
        if sha(root/name)!=digest:raise ValueError('Frozen implementation changed: '+name)


def block_interval(values, config):
    values=np.asarray(values);n=len(values)
    if n<config['bootstrap_block']*2:raise ValueError('Too few days for block uncertainty estimate')
    if np.all(values==values[0]):return [float(values[0]),float(values[0])]
    rng=np.random.default_rng(config['bootstrap_seed']);block=config['bootstrap_block']
    starts=rng.integers(0,n,size=(config['bootstrap_repeats'],int(np.ceil(n/block))))
    indices=((starts[:,:,None]+np.arange(block))%n).reshape(len(starts),-1)[:,:n]
    return np.quantile(values[indices].mean(axis=1),[.025,.975]).tolist()


def choose_candidate(training, validation, candidates):
    if any(stage[name]['baseline_unresolved'] for stage in [training,validation] for name in candidates):
        raise ValueError('Reference portfolio unresolved; cannot select or unlock holdout')
    eligible=[];checks={}
    for name in candidates:
        a,b=training[name],validation[name]
        checks[name]={'train_trades':a['trades']>=80,'train_positive':a['return']>0,
                      'train_excess':a['excess_return'] is not None and a['excess_return']>0,'validation_positive':b['return']>0,
                      'validation_excess':b['excess_return'] is not None and b['excess_return']>0,'validation_win_rate':(b['win_rate'] or 0)>=.5,
                      'no_unresolved':a['unresolved']==0 and b['unresolved']==0,
                      'benchmarks_resolved':a['baseline_unresolved']==0 and b['baseline_unresolved']==0}
        if all(checks[name].values()):eligible.append(name)
    comparable=[name for name in candidates if validation[name]['information_ratio'] is not None]
    if not comparable:raise ValueError('No valid validation ranking; cannot unlock holdout')
    ranked=sorted(eligible or comparable,key=lambda name:(-validation[name]['information_ratio'],name))
    return {'strategy_id':ranked[0],'eligible_in_development':bool(eligible),'checks':checks,
            'ranking':ranked,'selection_basis':'validation daily active-return information ratio after training gates'}


def phase_daily_returns(nav_by_phase, capital):
    nav=np.asarray(nav_by_phase,dtype=float)
    previous=np.column_stack([np.full(len(nav),capital),nav[:,:-1]])
    return (nav/previous-1).mean(axis=0)


def promotion_checks(selected_ok,current,baseline,stress,stress_baseline,interval):
    return {'development_passed':selected_ok,'enough_days':current['signal_days']>=60,
            'enough_trades':current['trades']>=80,'positive_return':current['return']>0,
            'win_rate':(current['win_rate'] or 0)>=.5,
            'positive_excess':current['excess_return'] is not None and current['excess_return']>0,
            'all_phases_positive_excess':current['phase_excess'] is not None and min(current['phase_excess'])>0,
            'positive_stress_return':stress['return']>0,
            'block_interval_above_zero':interval[0] is not None and interval[0]>0,
            'no_unresolved':current['unresolved']==0,'benchmark_resolved':baseline['unresolved']==0,
            'stress_resolved':stress['unresolved']==0,'stress_benchmark_resolved':stress_baseline['unresolved']==0}


def evaluate(market, name, bounds, horizon, config):
    indices=np.flatnonzero((market['dates']>=bounds[0])&(market['dates']<=bounds[1]))
    if len(indices)<=config['purge_sessions']+horizon+1:raise ValueError('Stage too short')
    phases=[simulate(market,market['pick_'+name],int(indices[0]),int(indices[-1]),horizon,p,config) for p in range(horizon)]
    phase_nav=[[row['nav'] for row in phase['equity']] for phase in phases]
    nav=np.mean(phase_nav,axis=0)
    returns=phase_daily_returns(phase_nav,config['capital'])
    trades=[dict(t,phase=i) for i,phase in enumerate(phases) for t in phase['trades']]
    profits=np.array([t['pnl'] for t in trades]);net=np.array([t['net_return'] for t in trades])
    wealth=np.r_[config['capital'],nav]
    summary={'return':float(nav[-1]/config['capital']-1),
        'phase_returns':[p['summary']['return'] for p in phases],
        'max_drawdown':float((wealth/np.maximum.accumulate(wealth)-1).min()),
        'worst_phase_drawdown':min(p['summary']['max_drawdown'] for p in phases),
        'trades':len(trades),'win_rate':float((profits>0).mean()) if len(profits) else None,
        'mean_trade':float(net.mean()) if len(net) else None,'profit_factor':cash_profit_factor(trades),
        'unresolved':sum(p['summary']['unresolved'] for p in phases),
        'mean_fees':float(np.mean([p['summary']['fees'] for p in phases])),
        'calendar_days':len(indices),'signal_days':len(indices)-config['purge_sessions']}
    return {'summary':summary,'phases':phases,'daily_returns':returns.tolist(),
            'equity':[{'date':str(market['dates'][index]),'nav':float(value)} for index,value in zip(indices,nav)],'trades':trades}


def compare(result, baseline):
    if [x['date'] for x in result['equity']]!=[x['date'] for x in baseline['equity']]:raise ValueError('Benchmark dates differ')
    active=np.array(result['daily_returns'])-np.array(baseline['daily_returns'])
    summary=result['summary'];summary['baseline_unresolved']=baseline['summary']['unresolved']
    if summary['unresolved'] or summary['baseline_unresolved'] or not summary['trades'] or not baseline['summary']['trades']:
        summary.update(excess_return=None,information_ratio=None,phase_excess=None,relative_valid=False)
        return None
    summary['relative_valid']=True;summary['excess_return']=summary['return']-baseline['summary']['return']
    std=float(active.std(ddof=1))
    summary['information_ratio']=float(active.mean()/std*np.sqrt(252)) if std>0 else 0.
    summary['phase_excess']=[a-b for a,b in zip(summary['phase_returns'],baseline['summary']['phase_returns'])]
    return active


def save_result(folder, name, result):
    folder.mkdir(parents=True,exist_ok=True)
    atomic_json(folder/(name+'.json'),result)
    pd.DataFrame(result['trades']).to_csv(folder/(name+'-trades.csv'),index=False)
    pd.DataFrame(result['equity']).to_csv(folder/(name+'-equity.csv'),index=False)


def freeze(panel, output):
    output.mkdir(parents=True,exist_ok=True)
    if (output/'frozen.json').exists():raise ValueError('This experiment is already frozen')
    panel_info=json.loads(panel.with_suffix('.json').read_text())
    verify_hashes(APP,panel_info['code'])
    if sha(panel)!=panel_info['panel_sha256'] or sha(APP/'research/protocol.json')!=panel_info['protocol_sha256']:
        raise ValueError('Panel or protocol differs from verified preparation')
    atomic_json(output/'frozen.json',{'code':{f:sha(APP/f) for f in SOURCES},
        'panel_sha256':sha(panel),'panel_metadata_sha256':sha(panel.with_suffix('.json')),
        'data_revision':panel_info['data_revision'],'status':'frozen before performance evaluation'})
    print('Frozen source and data hashes:',sha(output/'frozen.json'),flush=True)


def load_frozen(panel, output):
    frozen=json.loads((output/'frozen.json').read_text());verify_hashes(APP,frozen['code'])
    if sha(panel)!=frozen['panel_sha256'] or sha(panel.with_suffix('.json'))!=frozen['panel_metadata_sha256']:
        raise ValueError('Frozen input panel changed')
    with np.load(panel,allow_pickle=False) as data:market={k:data[k] for k in data.files}
    return market,json.loads((APP/'research/protocol.json').read_text())


def development(panel, output):
    if (output/'selection.json').exists():raise ValueError('Selection already exists; do not overwrite its history')
    market,config=load_frozen(panel,output);summaries={};h=config['primary_horizon']
    names=[config['benchmark'],*config['candidates']]
    for stage in ['train','validation']:
        baseline=evaluate(market,config['benchmark'],config[stage],h,config)
        summaries[stage]={}
        for name in names:
            result=baseline if name==config['benchmark'] else evaluate(market,name,config[stage],h,config)
            compare(result,baseline);save_result(output/stage,name,result);summaries[stage][name]=result['summary']
            print(stage,name,json.dumps(result['summary'],ensure_ascii=False),flush=True)
    selected=choose_candidate(summaries['train'],summaries['validation'],config['candidates'])
    selected['frozen_sha256']=sha(output/'frozen.json')
    atomic_json(output/'selection.json',selected)
    atomic_json(output/'development-seal.json',{'selection_sha256':sha(output/'selection.json'),
                 'frozen_sha256':sha(output/'frozen.json')})
    print('Frozen candidate:',selected['strategy_id'],'eligible:',selected['eligible_in_development'],flush=True)


def holdout(panel, output):
    if (output/'holdout-summary.json').exists():raise ValueError('Holdout was already evaluated; keep its first result')
    market,config=load_frozen(panel,output)
    seal=json.loads((output/'development-seal.json').read_text())
    if seal['selection_sha256']!=sha(output/'selection.json') or seal['frozen_sha256']!=sha(output/'frozen.json'):
        raise ValueError('Frozen selection was altered')
    selected=json.loads((output/'selection.json').read_text());name=selected['strategy_id'];h=config['primary_horizon']
    if name not in config['candidates']:raise ValueError('Unregistered selected candidate')
    baseline=evaluate(market,config['benchmark'],config['holdout'],h,config)
    result=evaluate(market,name,config['holdout'],h,config);active=compare(result,baseline)
    compare(baseline,baseline);save_result(output/'holdout',config['benchmark'],baseline);save_result(output/'holdout',name,result)
    comparisons={name:result['summary'],config['benchmark']:baseline['summary']}
    for legacy in ['legacy_leaders','legacy_pullback','legacy_golden_pit']:
        other=evaluate(market,legacy,config['holdout'],h,config);compare(other,baseline)
        save_result(output/'holdout',legacy,other);comparisons[legacy]=other['summary']
    stress_config=dict(config,slippage=config['slippage']*2)
    stressed=evaluate(market,name,config['holdout'],h,stress_config)
    stress_base=evaluate(market,config['benchmark'],config['holdout'],h,stress_config)
    compare(stressed,stress_base);save_result(output/'stress',name,stressed);save_result(output/'stress',config['benchmark'],stress_base)
    diagnostics={}
    for horizon in config['diagnostic_horizons']:
        alternate=evaluate(market,name,config['holdout'],horizon,config)
        reference=evaluate(market,config['benchmark'],config['holdout'],horizon,config)
        compare(alternate,reference);save_result(output/f'horizon-{horizon}',name,alternate)
        save_result(output/f'horizon-{horizon}',config['benchmark'],reference);diagnostics[str(horizon)]=alternate['summary']
    interval=block_interval(active,config) if active is not None else [None,None]
    checks=promotion_checks(selected['eligible_in_development'],result['summary'],baseline['summary'],
                            stressed['summary'],stress_base['summary'],interval)
    summary={'selected':name,'name':NAMES[name],'comparisons':comparisons,'stress':stressed['summary'],
             'diagnostic_horizons':diagnostics,'daily_active_mean_95_interval':interval,
             'checks':checks,'passed_research_gate':all(checks.values()),
             'frozen_sha256':sha(output/'frozen.json'),'selection_sha256':sha(output/'selection.json')}
    atomic_json(output/'holdout-summary.json',summary)
    pd.DataFrame([dict(strategy=k,**v) for k,v in comparisons.items()]).to_csv(output/'comparison.csv',index=False)
    print(json.dumps(summary,ensure_ascii=False,indent=2),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('phase',choices=['freeze','development','holdout'])
    parser.add_argument('--panel',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();{'freeze':freeze,'development':development,'holdout':holdout}[args.phase](args.panel.resolve(),args.output.resolve())
