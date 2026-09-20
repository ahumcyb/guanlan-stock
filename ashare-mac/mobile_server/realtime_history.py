"""Fixed run records and notification bindings, separate from live queue state."""
import hashlib
import json
import re
from pathlib import Path
from .artifacts import checked_file,atomic_json
from .queue import canonical_uuid
from engine.close_proof import valid_date

MAX_RUNS=1000
MAX_EVENTS=3000


def prune(folder,maximum,protected=()):
    files=sorted((p for p in folder.glob('*.json') if p.is_file() and not p.is_symlink()),key=lambda p:p.stat().st_mtime,reverse=True)
    keep=set(protected)
    for path in files:
        if len(keep)>=maximum:break
        keep.add(path.name)
    for path in files:
        if path.name not in keep:path.unlink()


def valid_slot(slot):
    if not isinstance(slot,str):return False
    if slot.startswith('manual-'):return canonical_uuid(slot[7:])
    return bool(re.fullmatch(r'\d{8}-(0910|1430|1445|1450)',slot) and valid_date(slot[:8]))


def run_state(report):
    if (not report.get('run_state') and report.get('status')=='blocked' and str(report.get('slot','')).startswith('manual-')
            and str(report.get('message','')).startswith('当前不在')):return 'waiting'
    return report.get('run_state') or {'ready':'complete','empty':'complete','blocked':'data_incomplete','closed':'closed'}[report['status']]


def summary(report):
    result={**{k:report[k] for k in ['slot','date','generated_at','kind','status','message','executor']},
            'run_state':run_state(report),
            'strategy_counts':{k:len(report['strategies'].get(k,[])) for k in ['overnight','golden']}}
    if report.get('orderflow') is not None:
        result['orderflow_status']=report['orderflow']['status']
        result['strategy_counts']['orderflow']=len(report['orderflow']['candidates'])
    if report.get('bottom_volume') is not None:
        result['bottom_status']=report['bottom_volume']['status']
        result['strategy_counts']['bottom_volume']=len(report['bottom_volume']['candidates'])
    return result


class RealtimeArchive:
    def __init__(self,root):self.root=Path(root).resolve()

    def collect(self,state):
        runs=self.root/'run-archive';events=self.root/'event-archive'
        for folder in [runs,events]:folder.mkdir(exist_ok=True,mode=0o770)
        previous=self.history();known={row['slot']:row for row in previous}
        for report in state.get('runs',[]):
            if not valid_slot(report.get('slot')):raise ValueError('历史轮次无效')
            slot=report['slot'];path=runs/(slot+'.json')
            if not path.exists():
                frozen={k:v for k,v in report.items() if k!='ai'};frozen['run_state']=run_state(report)
                raw=json.dumps(frozen,ensure_ascii=False,sort_keys=True,allow_nan=False,separators=(',',':'))
                atomic_json(path,dict(report=frozen,sha256=hashlib.sha256(raw.encode()).hexdigest()))
            if report['kind']!='prepare':known[slot]=summary(report)
        current=sorted(known.values(),key=lambda row:(row['generated_at'],row['slot']),reverse=True)[:min(90,MAX_RUNS)]
        if current!=previous:atomic_json(self.root/'history.json',current)
        for event in state.get('events',[]):
            if not canonical_uuid(event.get('id')):raise ValueError('历史提醒编号无效')
            path=events/(event['id']+'.json')
            if not path.exists() or json.loads(checked_file(self.root,path,65536).read_text())!=event:atomic_json(path,event)
        prune(runs,MAX_RUNS,{row['slot']+'.json' for row in current})
        prune(events,MAX_EVENTS)

    def history(self):
        path=self.root/'history.json'
        if not path.exists():return []
        rows=json.loads(checked_file(self.root,path,128*1024).read_text())
        if not isinstance(rows,list) or len(rows)>90 or any(not valid_slot(row.get('slot')) for row in rows):raise ValueError('历史列表无效')
        return rows

    def run(self,slot):
        if not valid_slot(slot):raise ValueError('历史轮次无效')
        value=json.loads(checked_file(self.root,self.root/'run-archive'/(slot+'.json'),256*1024).read_text())
        report=value['report'];raw=json.dumps(report,ensure_ascii=False,sort_keys=True,allow_nan=False,separators=(',',':'))
        if report.get('slot')!=slot or hashlib.sha256(raw.encode()).hexdigest()!=value.get('sha256'):raise ValueError('历史轮次校验失败')
        return report

    def event_detail(self,identity):
        if not canonical_uuid(identity):raise ValueError('历史提醒编号无效')
        event=json.loads(checked_file(self.root,self.root/'event-archive'/(identity+'.json'),65536).read_text())
        if event.get('id')!=identity:raise ValueError('历史提醒校验失败')
        report=None;message='这条旧提醒没有保存对应轮次，以下保留当时的原始消息。'
        if event.get('run_id'):
            try:report=self.run(event['run_id']);message='已定位到这条提醒对应的原始轮次。'
            except (OSError,ValueError,KeyError):message='对应轮次暂不可读取，保留提醒原文，请稍后重试。'
        return dict(event=event,report=report,message=message)
