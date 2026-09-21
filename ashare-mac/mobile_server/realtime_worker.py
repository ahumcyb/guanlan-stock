from .datta_ownership import job_environment
"""Independent intraday service, so expensive history jobs cannot block alert scheduling."""
import argparse
import json
import hashlib
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from .artifacts import atomic_json
from .mac_worker import WorkerClient, LostLease,WorkerRequestError
from .realtime import RealtimeStore


STAGE_LABELS={'sync':'服务器行情同步','credentials':'行情凭据读取','history':'历史基准与流通股本准备',
              'quotes':'实时行情获取','index':'沪深300行情获取','minutes':'分钟行情获取',
              'validation':'实时结果校验','runtime':'盘中计算','publication':'结果提交与服务端校验'}


def blocked_report(job,stage,code,computed_saved=False):
    stage=stage if stage in STAGE_LABELS else 'runtime'
    return dict(schema_version=1,date=job['date'],previous_date=job['previous_date'],generated_at=time.time(),
        kind=job['kind'],strategies={'overnight':[],'golden':[]},reviews=[],warnings=[],status='blocked',
        failure_stage=stage,failure_code=code,computed_result_saved=computed_saved,
        message=(STAGE_LABELS[stage]+'未完成'+('（HTTP '+code[5:]+'）' if code.startswith('http_') else '')+
                 (('；本机已保留这次结果，本轮未发布候选' if computed_saved else '；本轮未发布候选，请查看运行记录') if stage=='publication' else '，本轮未生成候选；请查看运行记录后重试')))


def execute(market, cache, job, config=None, progress=None):
    progress=progress or (lambda stage:None)
    if config:
        progress('sync')
        from engine.remote import verify_files
        from engine.snapshot_protocol import validate_manifest
        ready=False
        try:
            header=validate_manifest(json.loads((Path(market)/'manifest.json').read_text()))
            if header['as_of']>=job['previous_date']:
                verify_files(Path(market),header);ready=True
        except (OSError,ValueError,KeyError):pass
        if not ready:
            # The earlier daily job pre-caches its built tables; sync only activates
            # them after the server confirms the immutable revision.
            process=subprocess.Popen([sys.executable,'-m','engine.remote','--config',config['ssh_config'],
                '--cache',str(Path(config['workspace'])/'market')],start_new_session=True)
            try:
                if process.wait(timeout=180):raise ValueError('镜像同步未完成')
            finally:
                if process.poll() is None:
                    os.killpg(process.pid,signal.SIGTERM)
                    try:process.wait(timeout=5)
                    except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.wait()
    from engine.intraday_runner import run
    return run(market, cache, job['kind'], job.get('previous_candidates', []),progress=progress,slot_id=job.get('id'))


def execute_report(market,cache,job,config=None):
    start=time.monotonic();stage='runtime'
    folder=Path(cache)/'diagnostics'
    try:folder.mkdir(parents=True,exist_ok=True,mode=0o700)
    except OSError:pass
    path=folder/(hashlib.sha256(str(job['id']).encode()).hexdigest()[:24]+'.json')
    record=dict(schema_version=1,slot=str(job['id'])[:80],kind=job['kind'],started_at=time.time())
    def save(status,**values):
        record.update(stage=stage,status=status,elapsed_seconds=round(time.monotonic()-start,3),**values)
        try:atomic_json(path,record)
        except OSError:pass
    def progress(value):
        nonlocal stage
        stage=value if value in STAGE_LABELS else 'runtime';save('running')
    try:
        report=execute(market,cache,job,config,progress=progress)
        save(report['status'],quote_diagnostics=report.get('quote_diagnostics',{}),
             failure_code=report.get('failure_code'))
        return report
    except Exception as error:
        # The exception message can contain provider content or credentials. Do not persist it.
        save('blocked',exception_type=type(error).__name__[:80],failure_code='execution_error')
        return blocked_report(job,stage,'execution_error')
    finally:
        try:
            for old in sorted(folder.glob('*.json'),key=lambda p:p.stat().st_mtime)[:-30]:
                if old!=path:old.unlink()
        except OSError:pass


def run_job(claim, renew, publish, failure, market, cache, config_path=None):
    stop = threading.Event();lost = threading.Event();process = None;stage='runtime';computed_saved=False
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
            process = subprocess.Popen(arguments, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,env=job_environment(claim))
            deadline = time.monotonic() + 240
            while process.poll() is None:
                if lost.wait(.5):
                    raise LostLease()
                if time.monotonic() > deadline:
                    raise TimeoutError('盘中计算超时')
            if process.returncode or not result.is_file() or result.stat().st_size > 128 * 1024:
                raise ValueError('盘中计算未完成')
            if lost.is_set():
                raise LostLease()
            report=json.loads(result.read_text())
            try:
                computed=Path(cache)/'computed';computed.mkdir(exist_ok=True,mode=0o700)
                saved=computed/(hashlib.sha256(claim['id'].encode()).hexdigest()[:24]+'.json')
                atomic_json(saved,report);saved.chmod(0o600);computed_saved=True
                for old in sorted(computed.glob('*.json'),key=lambda p:p.stat().st_mtime)[:-30]:old.unlink()
            except (OSError,ValueError):pass
            stage='publication'
            if not publish(claim['lease'], report):
                raise LostLease()
            print('盘中结果已校验并同步', flush=True)
    except LostLease:
        print('盘中执行连接失效，丢弃迟到结果', flush=True)
    except Exception as error:
        code='http_'+str(error.status) if isinstance(error,WorkerRequestError) else ('execution_timeout' if isinstance(error,TimeoutError) else 'worker_error')
        try:
            if not publish(claim['lease'],blocked_report(claim,stage,code,computed_saved)):
                failure(claim['lease'])
        except Exception:
            try:failure(claim['lease'])
            except Exception:pass
        print(json.dumps(dict(event='realtime_failed',slot=claim['id'],failure_stage=stage,failure_code=code),ensure_ascii=False),flush=True)
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
        atomic_json(args.result, execute_report(args.market_root, args.cache, job, config));return
    if args.calendar:
        from engine.intraday_runner import read_calendar
        from engine.market_source import make_intraday_provider
        args.cache.mkdir(parents=True, exist_ok=True)
        RealtimeStore(args.root).calendar(read_calendar(args.market_root, args.cache, make_intraday_provider()));return
    if config:
        cache = Path(config['workspace']).parent / 'realtime-worker'
        market = Path(config['workspace']) / 'market/current'
        client = WorkerClient(config)
        def call(action, value=None):
            return client.request('/v1/worker/realtime/' + action, value or {})
        while True:
            try:
                cache.mkdir(parents=True, exist_ok=True, mode=0o700)
                from engine.datta_session import require_session
                require_session()
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
        from .daily import DailyStore
        daily=DailyStore(args.root)
        def service_pulse():
            while not stop.wait(5):
                try:
                    store.pulse('server')
                    daily.pulse()
                except Exception:
                    pass
        threading.Thread(target=service_pulse, daemon=True).start()
        def jev_loop():
            from .jev import process_one
            from .jev_daily import process_daily
            while not stop.wait(2):
                try:process_one(store)
                except Exception:pass
                try:process_daily(store)
                except Exception:pass
        threading.Thread(target=jev_loop,daemon=True).start()
        try:
            last_calendar = -21600  # Refresh on startup even just after the host boots.
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
                try:
                    daily.tick(args.market_root)
                except Exception:
                    print('收盘总结暂未完成，已保留有效记录，稍后继续',flush=True)
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
