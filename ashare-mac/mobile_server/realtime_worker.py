"""Independent intraday service, so expensive history jobs cannot block alert scheduling."""
import argparse
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from .artifacts import atomic_json
from .mac_worker import WorkerClient, LostLease
from .realtime import RealtimeStore


def execute(market, cache, job, config=None):
    if config:
        # Use the existing immutable download protocol, via its supported CLI.
        subprocess.run([sys.executable, '-m', 'engine.remote', '--config', config['ssh_config'],
                        '--cache', str(Path(config['workspace']) / 'market')], check=True, timeout=120)
    from engine.intraday_runner import run
    return run(market, cache, job['kind'], job.get('previous_candidates', []))


def run_job(claim, renew, publish, failure, market, cache, config_path=None):
    stop = threading.Event();lost = threading.Event();process = None
    def pulse():
        last = time.monotonic()
        while not stop.wait(15):
            try:
                if not renew(claim['lease']):
                    lost.set();return
                last = time.monotonic()
            except Exception:
                if time.monotonic() - last > 65:
                    lost.set();return
    thread = threading.Thread(target=pulse, daemon=True);thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix='run-', dir=cache) as folder:
            job_path = Path(folder) / 'job.json';result = Path(folder) / 'result.json'
            atomic_json(job_path, claim);job_path.chmod(0o600)
            arguments = [sys.executable, '-m', 'mobile_server.realtime_worker', '--execute', str(job_path), '--result', str(result),
                         '--market-root', str(market), '--cache', str(cache)]
            if config_path:
                arguments += ['--config', str(config_path)]
            process = subprocess.Popen(arguments, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            deadline = time.monotonic() + 240
            while process.poll() is None:
                if lost.wait(.5):
                    raise LostLease()
                if time.monotonic() > deadline:
                    raise ValueError('盘中计算超时')
            if process.returncode or not result.is_file() or result.stat().st_size > 128 * 1024:
                raise ValueError('盘中计算未完成')
            if lost.is_set():
                raise LostLease()
            if not publish(claim['lease'], json.loads(result.read_text())):
                raise LostLease()
            print('盘中结果已校验并同步', flush=True)
    except LostLease:
        print('盘中执行连接失效，丢弃迟到结果', flush=True)
    except Exception:
        try:
            failure(claim['lease'])
        except Exception:
            pass
        print('本轮盘中检查未完成，详情保留在 App 运行记录', flush=True)
    finally:
        stop.set();thread.join(timeout=1)
        if process is not None and process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL);process.wait()


def enrich_latest(store):
    from .notifications import deepseek_review
    settings = store.settings()
    if not settings['ai_enabled'] or not settings.get('deepseek_key'):
        return
    with store.lock():
        state = store.state()
        latest = state['runs'][-1] if state['runs'] else None
        if (not latest or latest.get('ai') or latest['kind'] != 'screen' or latest['status'] != 'ready'
                or not any(latest['strategies'].values()) or time.time() - latest['generated_at'] > 180):
            return
        latest['ai'] = {'status': 'pending', 'summary': '正在生成可选 AI 解读', 'risks': []};store.save(state)
        slot = latest['slot']
    result = deepseek_review(settings['deepseek_key'], settings['model'], latest)
    with store.lock():
        state = store.state()
        for report in state['runs']:
            if report['slot'] == slot:
                report['ai'] = result
        store.save(state)


def main(args):
    config = json.loads(args.config.read_text()) if args.config else None
    if args.execute:
        job = json.loads(args.execute.read_text())
        atomic_json(args.result, execute(args.market_root, args.cache, job, config));return
    if args.calendar:
        from engine.intraday_runner import read_calendar, IntradayProvider
        args.cache.mkdir(parents=True, exist_ok=True)
        RealtimeStore(args.root).calendar(read_calendar(args.market_root, args.cache, IntradayProvider()));return
    if config:
        cache = Path(config['workspace']).parent / 'realtime-worker'
        market = Path(config['workspace']) / 'market/current'
        client = WorkerClient(config)
        def call(action, value=None):
            return client.request('/v1/worker/realtime/' + action, value or {})
        while True:
            try:
                cache.mkdir(parents=True, exist_ok=True, mode=0o700)
                job = call('claim').get('job')
                if job:
                    run_job(job, lambda t: call('renew', {'lease': t})['accepted'],
                        lambda t, r: call('publish', {'lease': t, 'report': r})['accepted'],
                        lambda t: call('failure', {'lease': t}), market, cache, args.config)
            except KeyboardInterrupt:
                return
            except Exception:
                print('盘中节点暂未连接，稍后重试', flush=True)
            time.sleep(10)
    else:
        cache = args.cache;cache.mkdir(parents=True, exist_ok=True, mode=0o700)
        store = RealtimeStore(args.root);stop = threading.Event()
        def service_pulse():
            while not stop.wait(5):
                try:
                    store.pulse('server')
                except Exception:
                    pass
        threading.Thread(target=service_pulse, daemon=True).start()
        try:
            last_calendar = 0
            from .notifications import send_bark
            while True:
                if time.monotonic() - last_calendar > 21600:
                    try:
                        subprocess.run([sys.executable, '-m', 'mobile_server.realtime_worker', '--calendar', '--root', str(args.root),
                            '--market-root', str(args.market_root), '--cache', str(cache)], timeout=45, check=True,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        last_calendar = time.monotonic()
                    except Exception:
                        last_calendar = time.monotonic() - 21300
                store.pulse('server')
                notification = store.take_event()
                if notification:
                    event, key = notification;store.finish_event(event['id'], send_bark(key, event))
                job = store.claim('server')
                if job:
                    run_job(job, store.renew, store.publish, store.fail, args.market_root, cache)
                enrich_latest(store)
                time.sleep(3)
        finally:
            stop.set()


if __name__ == '__main__':
    parser = argparse.ArgumentParser();parser.add_argument('--config', type=Path)
    parser.add_argument('--root', type=Path);parser.add_argument('--market-root', type=Path);parser.add_argument('--cache', type=Path)
    parser.add_argument('--execute', type=Path);parser.add_argument('--result', type=Path);parser.add_argument('--calendar', action='store_true')
    args = parser.parse_args()
    if args.config and args.config.stat().st_mode & 0o077:
        raise SystemExit('Worker configuration must have mode 600')
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    main(args)
