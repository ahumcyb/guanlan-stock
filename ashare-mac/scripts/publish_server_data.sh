#!/bin/bash
# Administrative publication. SSH asks for authentication; no credentials stored.
set -euo pipefail
cd "$(dirname "$0")/.."
case "${1:-}" in
  --refresh) .venv/bin/python -m engine.update --data-root ../data --overlay data ;;
  "") ;;
  *) printf '用法：bash scripts/publish_server_data.sh [--refresh]\n' >&2; exit 2 ;;
esac
.venv/bin/python -m engine.package_data --data-root ../data --overlay data --output .cache/deploy
GUANLAN_REVISION="$(.venv/bin/python - <<'PY'
import json,re
from pathlib import Path
revision=json.loads(Path('.cache/deploy/latest.json').read_text())['revision']
if not re.fullmatch(r'\d{8}-[a-f0-9]{16}',revision):raise ValueError('Invalid revision')
print(revision)
PY
)"
GUANLAN_SOCKET_DIR="$(mktemp -d /tmp/guanlan-publish.XXXXXX)"
GUANLAN_SOCKET="$GUANLAN_SOCKET_DIR/control"
GUANLAN_SSH=(-o StrictHostKeyChecking=yes -o ControlMaster=auto -o "ControlPath=$GUANLAN_SOCKET" -o ControlPersist=600)
cleanup() {
  ssh -o "ControlPath=$GUANLAN_SOCKET" -O exit root@106.14.125.189 >/dev/null 2>&1 || true
  rmdir "$GUANLAN_SOCKET_DIR" 2>/dev/null || true
}
trap cleanup EXIT
ssh "${GUANLAN_SSH[@]}" root@106.14.125.189 'test -f /opt/guanlan-data/publish.py && test -d /srv/guanlan-data/staging'
rsync -rt --partial -e "ssh -o StrictHostKeyChecking=yes -o ControlPath=$GUANLAN_SOCKET" \
  ".cache/deploy/$GUANLAN_REVISION" root@106.14.125.189:/srv/guanlan-data/staging/
ssh "${GUANLAN_SSH[@]}" root@106.14.125.189 \
  "python3 /opt/guanlan-data/publish.py --root /srv/guanlan-data --revision $GUANLAN_REVISION"
printf '发布完成：%s。Mac 中点击“同步服务器”。\n' "$GUANLAN_REVISION"
