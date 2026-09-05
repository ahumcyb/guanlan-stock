"""Native Mac bridge; JSON settings enter stdin and public status leaves stdout."""
import argparse
import json
import sys
from pathlib import Path
from .mac_worker import WorkerClient


if __name__ == '__main__':
    parser = argparse.ArgumentParser();parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('action', choices=['state', 'settings', 'scan', 'test']);args = parser.parse_args()
    try:
        if args.config.stat().st_mode & 0o077:
            raise ValueError()
        client = WorkerClient(json.loads(args.config.read_text()))
        value = json.loads(sys.stdin.read(4097)) if args.action == 'settings' else {}
        result = client.request('/v1/realtime' if args.action=='state' else '/v1/realtime/'+args.action,
                                value, method='GET' if args.action=='state' else 'POST')
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    except Exception:
        print(json.dumps({'error': '实时服务暂不可用，请检查节点连接或设置'}));sys.exit(1)
