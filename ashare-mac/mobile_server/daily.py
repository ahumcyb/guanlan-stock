"""Durable daily review workflow; API methods stay small and never call the model."""
import fcntl
import json
import os
import time
import uuid
from contextlib import contextmanager
from datetime import datetime,timedelta
from pathlib import Path
from engine.close_proof import valid_date,closing_cutoff,ZONE
from .artifacts import checked_file
from .queue import JobQueue,ACTIVE
from .realtime import RealtimeStore,durable_json
from .daily_facts import evidence_hash

RETRY_SECONDS=20*60
MAX_ATTEMPTS=12


def latest_due_date(calendar, timestamp):
    now=datetime.fromtimestamp(timestamp,ZONE);today=now.strftime('%Y%m%d')
    if not isinstance(calendar,list) or not calendar or len(calendar)>1800 or not all(valid_date(d) for d in calendar):return None
    if max(calendar)<today:return None  # An outdated calendar is not proof of a holiday.
    cutoff=(now if (now.hour,now.minute)>=(16,10) else now-timedelta(days=1)).strftime('%Y%m%d')
    dates=[d for d in calendar if d<=cutoff]
    return max(dates) if dates else None


def unavailable(message):
    return dict(status='unavailable',headline='收盘量价总结',market_view='量价数据已完成核验，详见下方事实卡片。',
                sector_view='',strategy_view='',watch_next='',risks=[message])


class DailyStore:
    def __init__(self,root,clock=time.time):
        self.base=Path(root).resolve();self.root=self.base/'jobs/daily'
        self.root.mkdir(parents=True,exist_ok=True,mode=0o770)
        (self.root/'reports').mkdir(exist_ok=True,mode=0o770)
        self.clock=clock;self.realtime=RealtimeStore(self.base,clock);self.queue=JobQueue(self.base/'jobs',clock)

    @contextmanager
    def lock(self,name='.lock',blocking=True):
        fd=os.open(self.root/name,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o660)
        with os.fdopen(fd,'a') as file:
            fcntl.flock(file,fcntl.LOCK_EX|(0 if blocking else fcntl.LOCK_NB));yield

    def state(self):
        path=self.root/'state.json'
        if not path.exists():return {'days':{}}
        value=json.loads(checked_file(self.root,path,2*1024*1024).read_text())
        if not isinstance(value,dict) or not isinstance(value.get('days'),dict) or any(not valid_date(d) for d in value['days']):
            raise ValueError('每日总结状态无效')
        return value

    def save(self,state):
        state['days']=dict(sorted(state['days'].items())[-400:])
        durable_json(self.root/'state.json',state)

    def settings(self):
        value=self.realtime.settings()
        return dict(enabled=value['daily_enabled'],notification_enabled=value['daily_notification_enabled'],
                    ai_enabled=value['daily_ai_enabled'],model=value['model'],
                    deepseek_configured=bool(value.get('deepseek_key')),bark_configured=bool(value.get('bark_key')))

    def configure(self,changes):
        allowed={'enabled','notification_enabled','ai_enabled','model','deepseek_key','clear_deepseek'}
        if not isinstance(changes,dict) or set(changes)-allowed:raise ValueError('收盘总结设置字段无效')
        mapping={'enabled':'daily_enabled','notification_enabled':'daily_notification_enabled','ai_enabled':'daily_ai_enabled'}
        self.realtime.configure({mapping.get(key,key):value for key,value in changes.items()})
        return self.settings()

    def target(self):return latest_due_date(self.realtime.calendar(),self.clock())

    def pulse(self):
        durable_json(self.root/'heartbeat.json',{'heartbeat':self.clock(),'version':'daily-1'})

    def online(self):
        path=self.root/'heartbeat.json'
        try:
            value=json.loads(checked_file(self.root,path,4096).read_text())
            return value.get('version')=='daily-1' and 0<=self.clock()-value.get('heartbeat',0)<45
        except (OSError,ValueError,TypeError):return False

    def report(self,date):
        if not valid_date(date):raise ValueError('总结日期无效')
        path=checked_file(self.root,self.root/'reports'/(date+'.json'),128*1024)
        report=json.loads(path.read_text())
        if (report.get('schema_version')!=1 or report.get('date')!=date or report.get('evidence',{}).get('date')!=date
                or report.get('evidence_sha256')!=evidence_hash(report['evidence'])):
            raise ValueError('收盘总结内容校验失败')
        return report

    def write_report(self,report):
        performance=report.get('evidence',{}).get('realtime_performance')
        if report.get('analysis',{}).get('status')=='unavailable' and performance:
            from .daily_realtime_performance import summary_text
            report=dict(report,analysis=dict(report['analysis'],strategy_view=summary_text(performance)))
        if not valid_date(report.get('date')) or len(json.dumps(report,ensure_ascii=False,allow_nan=False).encode())>128*1024:
            raise ValueError('收盘总结内容超出限制')
        durable_json(self.root/'reports'/(report['date']+'.json'),report)

    def public(self):
        state=self.state();target=self.target();latest=None;history=[]
        for date,row in sorted(state['days'].items(),reverse=True):
            if row.get('phase') not in ['ready','ai_pending']:continue
            try:report=self.report(date)
            except (OSError,ValueError,KeyError):continue
            if latest is None:latest=report
            history.append({'date':date,'headline':report['analysis']['headline'],'ai_status':report['analysis']['status']})
            if len(history)>=30:break
        current=state['days'].get(target,{})
        future=[closing_cutoff(d).timestamp() for d in self.realtime.calendar() if valid_date(d) and closing_cutoff(d).timestamp()>self.clock()]
        return dict(schema_version=1,settings=self.settings(),latest=latest,history=history,scheduler_online=self.online(),
            status={'date':target,'phase':current.get('phase','idle'),
                    'message':current.get('message','交易日 16:10 后自动核验行情并生成总结'),
                    'retry_at':current.get('retry_at'),'next_run_at':min(future) if future else None})

    def request(self,retry_ai=False,refresh_facts=False):
        if type(retry_ai) is not bool or type(refresh_facts) is not bool:raise ValueError('请求参数无效')
        date=self.target()
        if date is None:raise ValueError('尚无可生成的收盘日，请等待交易日历或 16:10 时点')
        with self.lock():
            state=self.state();now=self.clock()
            if now-state.get('manual_at',0)<60:raise BlockingIOError('请稍后重试')
            state['manual_at']=now
            row=state['days'].setdefault(date,self.new_day())
            if row.get('phase')=='ready' and refresh_facts:
                row.update(phase='waiting',manual=True,retry_at=0,attempts=0,
                           request_nonce=str(uuid.uuid4()),job_id=None,
                           message='等待重新核验行情与上一交易日精选结算')
            elif row.get('phase')=='ready' and retry_ai:
                row.update(phase='data_ready',manual=True,retry_ai=True,retry_at=0,message='等待重新生成 AI 解读')
            elif row.get('phase') not in ['ready','ai_pending']:
                row.update(phase='waiting',manual=True,retry_at=0,attempts=0,
                           request_nonce=str(uuid.uuid4()),job_id=None)
            self.save(state)
        return {'accepted':True,'date':date}

    @staticmethod
    def new_day():
        return {'phase':'waiting','attempts':0,'retry_at':0,'message':'等待收盘行情核验'}

    def notify(self,date,failure=False):
        settings=self.settings()
        if not settings['notification_enabled']:return
        with self.lock():
            state=self.state();row=state['days'][date]
            marker='failure_notified' if failure else 'notified'
            if row.get(marker):return
        with self.realtime.lock():
            events=self.realtime.state()
            title='观澜 · '+date[:4]+'-'+date[4:6]+'-'+date[6:]+' 收盘总结'
            body='当日行情仍未完整，打开观澜查看状态。' if failure else '收盘复盘已生成，点击查看市场量价、四套策略与分析。'
            self.realtime.event(events,title,body,'daily_review','daily-'+date+('-failure' if failure else ''),url='guanlan://daily?date='+date)
            self.realtime.save(events)
        with self.lock():
            state=self.state();state['days'][date][marker]=True;self.save(state)

    def tick(self,market_current,collect=None,analyze=None):
        self.pulse()
        try:
            with self.lock('.tick.lock',blocking=False):self._tick(market_current,collect,analyze)
        except BlockingIOError:
            return

    def _tick(self,market_current,collect,analyze):
        date=self.target()
        if date is None:return
        now=self.clock();settings=self.settings()
        with self.lock():
            state=self.state();row=state['days'].get(date)
            if not settings['enabled'] and not (row or {}).get('manual'):return
            row=state['days'].setdefault(date,self.new_day());self.save(state)
        if row['phase']=='ready':self.notify(date);return
        if row['phase']=='failed' and not row.get('manual'):return
        if row['phase']=='ai_pending':
            report=self.report(date)
            if report['analysis']['status']=='pending':
                if now-row.get('ai_started_at',now)<120:return
                report['analysis']=unavailable('上次 AI 调用结果不明，未自动重复调用；可手动重试。')
                self.write_report(report)
            self.finish(date,report);return
        if row.get('retry_at',0)>now:return
        queued=self.queue.state()
        if queued['status'] in ACTIVE:
            with self.lock():
                state=self.state();state['days'][date]['message']='等待当前数据任务完成；Mac 在线时优先计算';self.save(state)
            return
        if row['phase']=='data_ready':
            report=self.report(date);evidence=report['evidence']
        else:
            if collect is None:
                from .daily_facts import collect_evidence
                collect=collect_evidence
            try:
                evidence=collect(self.base,market_current,date,now)
                if evidence.get('date')!=date:raise ValueError('收盘证据日期不一致')
            except Exception:
                # Neither an old current pointer nor an unverified full partition is accepted.
                if row.get('job_id')==queued.get('id') and row['phase']=='queued':
                    # The publisher writes its receipt just after marking the job complete.
                    # Allow that short handoff without delaying a valid review by 20 minutes.
                    if queued['status']=='completed' and row.get('receipt_waits',0)<6:
                        with self.lock():
                            state=self.state();state['days'][date].update(receipt_waits=row.get('receipt_waits',0)+1,
                                retry_at=now+5,message='行情已发布，正在确认收盘版本');self.save(state)
                        return
                    with self.lock():
                        state=self.state();state['days'][date].update(phase='waiting',retry_at=now+RETRY_SECONDS,
                            message='收盘行情未完成核验，20 分钟后重试');self.save(state)
                    return
                deadline=closing_cutoff(date)+timedelta(hours=4,minutes=20)
                late_initial=row['attempts']==0
                if row['attempts']>=MAX_ATTEMPTS or now>deadline.timestamp() and not row.get('manual') and not late_initial:
                    with self.lock():
                        state=self.state();state['days'][date].update(phase='failed',message='当日行情仍未完整，未生成当日结论；可手动重试');self.save(state)
                    self.notify(date,failure=True);return
                try:
                    request_id=str(uuid.uuid5(uuid.NAMESPACE_URL,f'guanlan:daily:{date}:{row.get("request_nonce", "scheduled")}:{row["attempts"]+1}'))
                    job=self.queue.submit('refresh',request_id,expected_as_of=date)
                except BlockingIOError:return
                if job.get('expected_as_of')!=date:return
                with self.lock():
                    state=self.state();state['days'][date].update(phase='queued',job_id=job['id'],attempts=row['attempts']+1,
                        receipt_waits=0,message='已提交目标日行情更新，优先交给 Mac');self.save(state)
                return
            report={'schema_version':1,'date':date,'generated_at':now,'evidence':evidence,
                    'evidence_sha256':evidence_hash(evidence),'analysis':unavailable('等待 AI 解读')}
        private=self.realtime.settings()
        if (not private['daily_ai_enabled'] or not private.get('deepseek_key')
                or not private['daily_enabled'] and not row.get('manual')):
            report['analysis']=unavailable('AI 分析未启用或尚未配置 Key，已保留量价与策略摘要。')
            self.write_report(report);self.finish(date,report);return
        report['analysis']=dict(unavailable('正在生成 DeepSeek 分析'),status='pending')
        self.write_report(report)
        with self.lock():
            state=self.state();state['days'][date].update(phase='ai_pending',ai_started_at=now,
                message='收盘量价已核验，DeepSeek 正在生成分析',retry_ai=False);self.save(state)
        if analyze is None:
            from .notifications import deepseek_daily_review
            analyze=deepseek_daily_review
        try:report['analysis']=analyze(private['deepseek_key'],private['model'],evidence)
        except Exception:report['analysis']=unavailable('AI 分析暂不可用，已保留量价与策略摘要。')
        report['generated_at']=self.clock();self.write_report(report);self.finish(date,report)

    def finish(self,date,report):
        with self.lock():
            state=self.state();state['days'][date].update(phase='ready',manual=False,retry_at=0,
                message='收盘总结已完成' if report['analysis']['status']=='ready' else '量价总结已完成，AI 解读暂不可用')
            self.save(state)
        self.notify(date)
