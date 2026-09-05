#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
.venv/bin/python - <<'PY'
import os,plistlib
from pathlib import Path
root=Path.cwd();config=root/'settings/mobile-worker.json'
if not config.is_file() or config.stat().st_mode&0o077:raise ValueError('先生成权限为600的Mac计算节点配置')
logs=root/'.cache/mobile-worker';logs.mkdir(parents=True,exist_ok=True)
plist=Path.home()/'Library/LaunchAgents/local.guanlan.compute-worker.plist'
plist.parent.mkdir(parents=True,exist_ok=True)
value=dict(Label='local.guanlan.compute-worker',ProgramArguments=[str(root/'.venv/bin/python'),'-u','-m','mobile_server.mac_worker','--config',str(config)],WorkingDirectory=str(root),RunAtLoad=True,KeepAlive=True,ThrottleInterval=15,ProcessType='Background',StandardOutPath=str(logs/'worker.log'),StandardErrorPath=str(logs/'worker.log'),EnvironmentVariables={'OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1'})
with plist.open('wb') as output:plistlib.dump(value,output)
plist.chmod(0o644)
print('Mac计算节点启动配置已写入')
PY
GUANLAN_UID="$(id -u)"
if launchctl print "gui/$GUANLAN_UID/local.guanlan.compute-worker" >/dev/null 2>&1; then
  launchctl bootout "gui/$GUANLAN_UID/local.guanlan.compute-worker"
fi
launchctl bootstrap "gui/$GUANLAN_UID" "$HOME/Library/LaunchAgents/local.guanlan.compute-worker.plist"
printf 'Mac计算节点已启动，登录后自动运行。\n'
