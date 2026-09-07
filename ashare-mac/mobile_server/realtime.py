"""Small persisted realtime queue, with one fenced executor and a server outbox."""
import fcntl
import hmac
import json
import math
import os
import re
import secrets
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

from engine.intraday import CODE, SLOTS, due_slot, local_now
from .artifacts import atomic_json, checked_file

DEFAULTS = dict(enabled=True, notification_enabled=True, ai_enabled=False, model='deepseek-v4-flash',
                daily_enabled=False, daily_notification_enabled=True, daily_ai_enabled=True)
MODELS = {'deepseek-v4-flash', 'deepseek-v4-pro'}


def durable_json(path, value):
    temporary = path.with_name('.' + path.name + '-' + secrets.token_hex(4))
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o660)
        with os.fdopen(fd, 'w') as output:
            json.dump(value, output, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
            output.flush();os.fsync(output.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:os.fsync(directory)
        finally:os.close(directory)
    finally:
        if temporary.exists():temporary.unlink()


def bark_key(value):
    if not isinstance(value, str):
        raise ValueError('Bark 地址无效')
    parsed = urlsplit(value.strip())
    segments = parsed.path.strip('/').split('/')
    if (parsed.scheme != 'https' or parsed.netloc != 'api.day.app' or parsed.query or parsed.fragment
            or len(value) > 2048 or not 1 <= len(segments) <= 4
            or not re.fullmatch(r'[A-Za-z0-9_-]{16,128}', segments[0])):
        raise ValueError('请填写 Bark 首页的 https://api.day.app/设备密钥 地址')
    return segments[0]


def bounded_text(value, limit=300):
    return isinstance(value, str) and len(value) <= limit and not any(ord(c) < 32 and c not in '\n\t' for c in value)


def valid_number(value):
    return type(value) in (int, float) and math.isfinite(value)


def validate_report(report, job, now):
    if not isinstance(report, dict) or len(json.dumps(report, allow_nan=False).encode()) > 128 * 1024:
        raise ValueError('盘中结果格式无效')
    if (report.get('schema_version') != 1 or report.get('date') != job['date'] or report.get('kind') != job['kind']
            or report.get('previous_date') != job['previous_date']
            or not valid_number(report.get('generated_at')) or not -15 <= now - report['generated_at'] <= 180
            or report.get('status') not in ['ready', 'closed', 'empty', 'blocked']
            or not bounded_text(report.get('message'))):
        raise ValueError('盘中结果日期或状态无效')
    strategies = report.get('strategies')
    if not isinstance(strategies, dict) or set(strategies) != {'overnight', 'golden'}:
        raise ValueError('盘中策略无效')
    for key, rows in strategies.items():
        if not isinstance(rows, list) or len(rows) > 10:
            raise ValueError('盘中候选过多')
        seen = set()
        for row in rows:
            if not isinstance(row, dict) or row.get('strategy') != key:
                raise ValueError('候选策略无效')
            code = row.get('ts_code')
            if not isinstance(code, str) or not CODE.fullmatch(code) or code in seen:
                raise ValueError('候选代码无效')
            seen.add(code)
            if (not bounded_text(row.get('name'), 30) or not bounded_text(row.get('state'), 40)
                    or row.get('reference_date') != job['previous_date']
                    or not valid_number(row.get('price')) or row['price'] <= 0
                    or not valid_number(row.get('change')) or not 3 - 1e-8 <= row['change'] <= 5 + 1e-8
                    or not valid_number(row.get('quote_at')) or not -15 <= now - row['quote_at'] <= 180
                    or local_now(row['quote_at']).strftime('%Y%m%d') != job['date']):
                raise ValueError('候选价格或时间无效')
            for field in ['checks', 'pending']:
                if not isinstance(row.get(field), list) or len(row[field]) > 10 or not all(bounded_text(t, 100) for t in row[field]):
                    raise ValueError('候选说明无效')
    if report['status'] != 'ready' and any(strategies.values()):
        raise ValueError('失败结果不可携带候选')
    reviews = report.get('reviews')
    if not isinstance(reviews, list) or len(reviews) > 20:
        raise ValueError('复查格式无效')
    for row in reviews:
        if (not isinstance(row, dict) or not isinstance(row.get('ts_code'), str) or not CODE.fullmatch(row['ts_code'])
                or not bounded_text(row.get('name'), 30) or not bounded_text(row.get('note'), 100)
                or any(not valid_number(row.get(k)) for k in ['price', 'reference_price', 'change', 'quote_at'])
                or row['price'] <= 0 or row['reference_price'] <= 0 or not -15 <= now - row['quote_at'] <= 180):
            raise ValueError('复查行情无效')
    return report


class RealtimeStore:
    def __init__(self, root, clock=time.time):
        self.root = Path(root).resolve() / 'jobs/realtime'
        self.root.mkdir(parents=True, exist_ok=True, mode=0o770)
        self.clock = clock

    @contextmanager
    def lock(self):
        fd = os.open(self.root / '.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o660)
        with os.fdopen(fd, 'a') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            yield

    def read(self, name, default):
        file = self.root / name
        if not file.exists():
            return default
        return json.loads(checked_file(self.root, file, 2 * 1024 * 1024).read_text())

    def settings(self):
        return dict(DEFAULTS, **self.read('settings.json', {}))

    def configure(self, changes):
        if not isinstance(changes, dict) or set(changes) - {'enabled', 'notification_enabled', 'ai_enabled', 'model', 'bark_url', 'deepseek_key', 'clear_bark', 'clear_deepseek', 'daily_enabled', 'daily_notification_enabled', 'daily_ai_enabled'}:
            raise ValueError('设置字段无效')
        with self.lock():
            value = self.settings()
            for key in ['enabled', 'notification_enabled', 'ai_enabled', 'clear_bark', 'clear_deepseek', 'daily_enabled', 'daily_notification_enabled', 'daily_ai_enabled']:
                if key in changes and type(changes[key]) is not bool:
                    raise ValueError('设置值无效')
            for key in ['enabled', 'notification_enabled', 'ai_enabled', 'daily_enabled', 'daily_notification_enabled', 'daily_ai_enabled']:
                if key in changes:
                    value[key] = changes[key]
            if 'model' in changes:
                if changes['model'] not in MODELS:
                    raise ValueError('请选择支持的 DeepSeek 模型')
                value['model'] = changes['model']
            if changes.get('bark_url'):
                value['bark_key'] = bark_key(changes['bark_url'])
            if changes.get('deepseek_key'):
                key = changes['deepseek_key']
                if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,256}', key):
                    raise ValueError('DeepSeek API Key 格式无效')
                value['deepseek_key'] = key
            if changes.get('clear_bark'):
                value.pop('bark_key', None)
            if changes.get('clear_deepseek'):
                value.pop('deepseek_key', None);value['ai_enabled'] = False
            durable_json(self.root / 'settings.json', value)
        return self.public_settings()

    def public_settings(self):
        x = self.settings()
        return {**{k: x[k] for k in DEFAULTS}, 'bark_configured': bool(x.get('bark_key')), 'deepseek_configured': bool(x.get('deepseek_key'))}

    def state(self):
        return self.read('state.json', {'events': [], 'runs': [], 'done': []})

    def save(self, value):
        value['events'] = value.get('events', [])[-80:]
        value['runs'] = value.get('runs', [])[-15:]
        value['done'] = value.get('done', [])[-80:]
        durable_json(self.root / 'state.json', value)

    def calendar(self, dates=None):
        if dates is not None:
            if not isinstance(dates, list) or not all(isinstance(d, str) and re.fullmatch(r'\d{8}', d) for d in dates):
                raise ValueError('交易日历格式无效')
            atomic_json(self.root / 'calendar.json', sorted(set(dates)))
        return self.read('calendar.json', [])

    def pulse(self, executor):
        if executor not in ['mac', 'server']:
            raise ValueError('节点无效')
        with self.lock():
            nodes = self.read('nodes.json', {});nodes[executor + '_heartbeat'] = self.clock()
            atomic_json(self.root / 'nodes.json', nodes)

    def public(self):
        state = self.state();nodes = self.read('nodes.json', {});now = self.clock();lease = state.get('lease', {})
        return dict(schema_version=1, settings=self.public_settings(),
            mac_online=0 <= now - nodes.get('mac_heartbeat', 0) < 45,
            server_online=0 <= now - nodes.get('server_heartbeat', 0) < 45,
            running=lease.get('expires_at', 0) > now, executor=lease.get('executor', ''),
            schedule=['14:30 初筛', '14:45 复核', '14:50 提醒'],
            events=list(reversed(state['events'][-30:])), latest=state['runs'][-1] if state['runs'] else None,
            last_screen=next((r for r in reversed(state['runs']) if r['kind'] == 'screen'), None))

    def previous_candidates(self, date):
        days = [d for d in self.calendar() if d < date]
        if not days:
            return []
        for r in reversed(self.state()['runs']):
            if r['date'] == days[-1] and r['kind'] == 'screen' and r['status'] == 'ready':
                return list({x['ts_code']: x for rows in r['strategies'].values() for x in rows}.values())
        return []

    def request_scan(self):
        with self.lock():
            state = self.state();now = self.clock()
            if now - state.get('manual_requested_at', 0) < 60:
                raise BlockingIOError('请稍后再检查行情')
            state['manual_requested_at'] = now
            state['manual'] = {'id': 'manual-' + str(uuid.uuid4()), 'date': local_now(now).strftime('%Y%m%d'), 'kind': 'screen', 'scheduled_at': now}
            self.save(state)
        return {'accepted': True}

    def claim(self, executor):
        with self.lock():
            state = self.state();now = self.clock();settings = self.settings()
            nodes = self.read('nodes.json', {});nodes[executor + '_heartbeat'] = now
            atomic_json(self.root / 'nodes.json', nodes)
            if state.get('lease', {}).get('expires_at', 0) > now:
                return None
            if executor == 'server' and 0 <= now - nodes.get('mac_heartbeat', 0) < 45:
                return None
            calendar = self.calendar();job = due_slot(local_now(now), calendar) if settings['enabled'] else None
            if job is None and state.get('manual') and now - state['manual']['scheduled_at'] < 180:
                job = state['manual']
            if not job or job['id'] in state['done']:
                return None
            days = [d for d in calendar if d < job['date']]
            if not days:
                return None
            job = dict(job, previous_date=days[-1])
            lease = dict(job=job, executor=executor, token=secrets.token_hex(32), expires_at=now + 90)
            state['lease'] = lease;self.save(state)
            return dict(job, lease=lease['token'], previous_candidates=self.previous_candidates(job['date']))

    def owns(self, state, token):
        lease = state.get('lease', {})
        return isinstance(token, str) and hmac.compare_digest(lease.get('token', ''), token) and lease.get('expires_at', 0) > self.clock()

    def renew(self, token):
        with self.lock():
            state = self.state()
            if not self.owns(state, token):
                return False
            state['lease']['expires_at'] = self.clock() + 90
            nodes = self.read('nodes.json', {});nodes[state['lease']['executor'] + '_heartbeat'] = self.clock()
            atomic_json(self.root / 'nodes.json', nodes);self.save(state)
            return True

    def publish(self, token, report):
        with self.lock():
            state = self.state();now = self.clock()
            if not self.owns(state, token):
                return False
            job = state['lease']['job']
            if job['id'] in state['done']:
                return False
            report = validate_report(report, job, now)
            report = dict(report, slot=job['id'], executor=state['lease']['executor'])
            state['runs'].append(report);state['done'].append(job['id']);state.pop('lease', None)
            if state.get('manual', {}).get('id') == job['id']:
                state.pop('manual')
            # A late result stays inspectable but cannot generate a stale trading-time alert.
            if not job['id'].startswith('manual-') and now - job['scheduled_at'] < 180:
                self.result_event(state, report)
            self.save(state)
            return True

    def fail(self, token):
        with self.lock():
            state = self.state()
            if not self.owns(state, token):
                return False
            job = state['lease']['job'];now = self.clock()
            report = dict(schema_version=1, date=job['date'], previous_date=job['previous_date'], generated_at=now,
                kind=job['kind'], slot=job['id'], executor=state['lease']['executor'], status='blocked',
                strategies={'overnight': [], 'golden': []}, reviews=[], warnings=[],
                message='本轮数据获取或计算未完成，保留以前记录')
            state['runs'].append(report);state['done'].append(job['id']);state.pop('lease', None)
            if not job['id'].startswith('manual-'):
                self.result_event(state, report)
            self.save(state)
            return True

    def event(self, state, title, body, kind, dedup, url=None):
        if any(e.get('dedup') == dedup for e in state['events']):
            return
        event_id = str(uuid.uuid4())
        state['events'].append(dict(id=event_id, created_at=self.clock(), title=title, body=body, kind=kind,
            dedup=dedup, status='pending', attempts=0, url=url or 'guanlan://alerts/' + event_id))

    def result_event(self, state, report):
        if report['status'] == 'closed' or report['kind'] == 'prepare':
            return
        slot = report['slot'];clock = slot[-4:];label = clock[:2] + ':' + clock[2:]
        if report['status'] == 'blocked':
            self.event(state, '观澜 · 行情检查未完成', report['message'], 'data', report['date'] + '-data-failure')
        elif report['kind'] == 'review':
            if report['reviews']:
                body = '；'.join(r['name'] + f" {r['change']:+.2f}%" for r in report['reviews'][:5])
                self.event(state, '观澜 · ' + label + ' 昨日候选复查', body + '\n相对昨日筛选价，并非持仓收益；10:00前复查。', 'review', slot)
        else:
            rows = [r for batch in report['strategies'].values() for r in batch]
            body = ('本轮筛选已完成。' if rows else '本轮筛选已完成，暂无符合条件的候选。')
            body += '点击打开观澜，查看结果和行情时间。'
            self.event(state, '观澜 · ' + label + ' 筛选完成', body, 'screen', slot)

    def test_notification(self):
        with self.lock():
            state = self.state();now = self.clock()
            if now - state.get('test_at', 0) < 60:
                raise BlockingIOError('测试通知每分钟最多一次')
            state['test_at'] = now
            self.event(state, '观澜 · 通知连接测试', '这是一条测试通知，不含选股信号。点击进入观澜的实时提醒页。', 'test', str(uuid.uuid4()))
            self.save(state)
        return {'accepted': True}

    def take_event(self):
        with self.lock():
            state = self.state();settings = self.settings();now = self.clock()
            changed = False
            for event in state['events']:
                if event['status'] == 'sending' and now - event.get('sent_at', now) > 30:
                    event['status'] = 'unknown'  # Never replay a possibly delivered push after a crash.
                    changed = True
                if event['status'] not in ['pending', 'retry'] or event.get('retry_at', 0) > now:
                    continue
                notification_enabled=settings['daily_notification_enabled'] if event['kind']=='daily_review' else settings['notification_enabled']
                if not notification_enabled or not settings.get('bark_key'):
                    event['status'] = 'unconfigured';changed = True;continue
                lifetime=21600 if event['kind']=='daily_review' else 180
                if now - event['created_at'] > lifetime and event['kind'] != 'test':
                    event['status'] = 'expired';changed = True;continue
                event.update(status='sending', sent_at=now, attempts=event['attempts'] + 1)
                self.save(state)
                return dict(event), settings['bark_key']
            if changed:self.save(state)
            return None

    def finish_event(self, event_id, outcome):
        if outcome not in ['accepted', 'failed', 'unknown']:
            raise ValueError('通知响应无效')
        with self.lock():
            state = self.state()
            for event in state['events']:
                if event['id'] == event_id and event['status'] == 'sending':
                    event['status'] = 'retry' if outcome == 'failed' and event['attempts'] < 3 else outcome
                    event['retry_at'] = self.clock() + 30
            self.save(state)
