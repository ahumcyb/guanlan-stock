"""Mac bridge: private settings enter stdin; only public daily data leaves stdout."""
import argparse
import json
import sys
from pathlib import Path
from engine.close_proof import valid_date
from .mac_worker import WorkerClient

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--config',required=True,type=Path)
    parser.add_argument('action',choices=['state','report','settings','generate']);args=parser.parse_args()
    try:
        if args.config.stat().st_mode&0o077:raise ValueError()
        raw=sys.stdin.read(4097)
        if len(raw)>4096:raise ValueError()
        value=json.loads(raw) if raw else {}
        if not isinstance(value,dict):raise ValueError()
        client=WorkerClient(json.loads(args.config.read_text()))
        if args.action=='state':
            result=client.request('/v1/daily',method='GET')
        elif args.action=='report':
            if set(value)!={'date'} or not valid_date(value['date']):raise ValueError()
            result=client.request('/v1/daily/'+value['date'],method='GET')
        else:
            result=client.request('/v1/daily/'+args.action,value)
        print(json.dumps(result,ensure_ascii=False,allow_nan=False))
    except Exception:
        print(json.dumps({'error':'收盘总结服务暂不可用，请检查连接或设置'}));sys.exit(1)
