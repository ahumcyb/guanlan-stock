#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
.venv/bin/python - <<'PY'
import plistlib,os
from pathlib import Path
root=Path.cwd();config=root/'settings/mobile-worker.json'
if not config.is_file() or config.stat().st_mode&0o077:raise SystemExit('需要已有的私密 Mac 节点配置')
viewer=root/'settings/mobile-viewer.json';phone=root.parent/'ashare-ios/settings/手机连接.guanlan'
if not viewer.exists() and phone.is_file():
 with os.fdopen(os.open(viewer,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'wb') as output:output.write(phone.read_bytes())
logs=root/'.cache/realtime-worker';logs.mkdir(parents=True,exist_ok=True);logs.chmod(0o700)
plist=Path.home()/'Library/LaunchAgents/local.guanlan.realtime-worker.plist'
value=dict(Label='local.guanlan.realtime-worker',ProgramArguments=[str(root/'.venv/bin/python'),'-u','-m','mobile_server.realtime_worker','--config',str(config)],WorkingDirectory=str(root),RunAtLoad=True,KeepAlive=True,ThrottleInterval=15,ProcessType='Background',StandardOutPath=str(logs/'worker.log'),StandardErrorPath=str(logs/'worker.log'),EnvironmentVariables={'OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1'})
with plist.open('wb') as output:plistlib.dump(value,output)
plist.chmod(0o644)
PY
GUANLAN_UID="$(id -u)"
if launchctl print "gui/$GUANLAN_UID/local.guanlan.realtime-worker" >/dev/null 2>&1; then
  launchctl bootout "gui/$GUANLAN_UID/local.guanlan.realtime-worker"
fi
GUANLAN_LOADED=false
for GUANLAN_ATTEMPT in 1 2 3; do
  if launchctl bootstrap "gui/$GUANLAN_UID" "$HOME/Library/LaunchAgents/local.guanlan.realtime-worker.plist"; then
    GUANLAN_LOADED=true
    break
  fi
  sleep 1
done
test "$GUANLAN_LOADED" = true
printf '实时策略节点已启动，登录后自动运行。\n'
