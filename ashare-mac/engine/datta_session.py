"""Local fencing receipt written only by the Datta login supervisor."""
import json
import os
import time
from pathlib import Path
from .datta import DattaUnavailable


def shared_clock():
    # Python 3.9 macOS time.monotonic has a per-process origin.
    return time.clock_gettime(time.CLOCK_MONOTONIC)


def session_path():
    return Path(os.environ.get('GUANLAN_DATTA_SESSION',Path(__file__).resolve().parents[1]/'settings/datta-session.json'))


def require_session():
    try:
        path=session_path()
        if path.is_symlink() or path.stat().st_size>4096:raise ValueError()
        v=json.loads(path.read_text())
        if (v.get('phase')!='active' or v.get('clock')!='system_monotonic_v1' or not shared_clock()<v['valid_until_monotonic']
                or abs(time.time()-shared_clock()-v['boot_epoch'])>5):raise ValueError()
        expected=os.environ.get('GUANLAN_DATTA_EPOCH')
        if expected is not None and str(v.get('epoch'))!=expected:raise ValueError()
        try:os.kill(v['pid'],0)
        except PermissionError:pass  # Linux supervisor runs as a separate service user.
        return v
    except (OSError,ValueError,KeyError,TypeError):
        raise DattaUnavailable('本机尚未取得达塔登录权，等待主备协调；不会改用其他行情源') from None
