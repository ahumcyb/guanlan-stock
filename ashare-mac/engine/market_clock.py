"""Latest expected complete daily bar; no prices or network dependencies."""
from datetime import datetime
from .close_proof import ZONE,valid_date


def market_status(open_dates,now):
    if not isinstance(now,datetime) or now.tzinfo is None:raise ValueError('Market clock requires timezone')
    now=now.astimezone(ZONE);today=now.strftime('%Y%m%d')
    result=dict(expected_as_of=None,phase='unknown',calendar_covered=False,checked_at=now.timestamp(),next_screen_at=None)
    if (not isinstance(open_dates,list) or not open_dates or len(open_dates)>10000
            or any(not valid_date(d) for d in open_dates)):return result
    dates=sorted(set(open_dates))
    if today>dates[-1] or today<dates[0]:return result
    opened=today in dates;clock=(now.hour,now.minute)
    phase=('before_open' if clock<(9,30) else ('trading' if clock<(15,10) else 'after_close')) if opened else 'closed'
    expected=[d for d in dates if d<today or d==today and clock>=(15,10)]
    future=[]
    for date in dates:
        if date<today:continue
        day=datetime.strptime(date,'%Y%m%d').replace(tzinfo=ZONE)
        future=[day.replace(hour=h,minute=m).timestamp() for h,m in [(14,30),(14,45),(14,50)] if day.replace(hour=h,minute=m)>now]
        if future:break
    return dict(result,expected_as_of=expected[-1] if expected else None,phase=phase,calendar_covered=True,
                next_screen_at=future[0] if future else None)
