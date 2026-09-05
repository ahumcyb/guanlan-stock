#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
export DEVELOPER_DIR="${DEVELOPER_DIR:-/Applications/Xcode.app/Contents/Developer}"
GUANLAN_DEVICE_ID="${1:-}"
if [ -z "$GUANLAN_DEVICE_ID" ]; then
  GUANLAN_DEVICE_ID="$(python3 - <<'PY'
import json
from pathlib import Path
p=Path('settings/device.json')
if p.exists():print(json.loads(p.read_text())['identifier'])
PY
)"
fi
if [ -z "$GUANLAN_DEVICE_ID" ]; then
  printf '请先在 Xcode 完成个人团队签名，并指定已配对 iPhone 的设备 ID。\n' >&2
  exit 1
fi
mkdir -p .cache
xcrun devicectl device info details --device "$GUANLAN_DEVICE_ID" --json-output .cache/install-device.json --quiet
GUANLAN_UDID="$(python3 - <<'PY'
import json
from pathlib import Path
r=json.loads(Path('.cache/install-device.json').read_text())['result']
if r['connectionProperties']['pairingState']!='paired':raise SystemExit('请先在 Xcode 配对 iPhone。')
if r['deviceProperties'].get('developerModeStatus')!='enabled':raise SystemExit('请在 iPhone 开启开发者模式。')
print(r['hardwareProperties']['udid'])
PY
)"
xcodebuild -quiet -project Guanlan.xcodeproj -scheme Guanlan -configuration Debug \
  -sdk iphoneos -destination "id=$GUANLAN_UDID" -derivedDataPath build/DerivedData \
  -allowProvisioningUpdates -allowProvisioningDeviceRegistration build
xcrun devicectl device install app --device "$GUANLAN_DEVICE_ID" \
  build/DerivedData/Build/Products/Debug-iphoneos/Guanlan.app
if [ -f settings/手机连接.guanlan ]; then
  xcrun devicectl device copy to --device "$GUANLAN_DEVICE_ID" --source settings/手机连接.guanlan \
    --destination Documents/Pairing.guanlan --domain-type appDataContainer \
    --domain-identifier local.guanlan.ios.bennie --quiet
fi
xcrun devicectl device process launch --device "$GUANLAN_DEVICE_ID" --terminate-existing local.guanlan.ios.bennie
printf '观澜已安装并打开。配对成功后也可通过同一 Wi-Fi 更新签名。\n'
