#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -x .venv/bin/python ]; then bash scripts/setup.sh; fi
GUANLAN_APP_DIR="$PWD/build/观澜选股.app"
mkdir -p "$GUANLAN_APP_DIR/Contents/MacOS" "$GUANLAN_APP_DIR/Contents/Resources"
swiftc -O -parse-as-library -target arm64-apple-macosx14.0 \
  -framework SwiftUI -framework AppKit -framework Charts \
  macos/*.swift ../ashare-ios/Sources/Core/Connection.swift ../ashare-ios/Sources/Core/Snapshots.swift \
  ../ashare-ios/Sources/Core/Watchlist.swift -o "$GUANLAN_APP_DIR/Contents/MacOS/Guanlan"
.venv/bin/python - <<'PY'
import json,plistlib
from pathlib import Path
root=Path.cwd(); app=root/'build'/'观澜选股.app'/'Contents'
with (app/'Info.plist').open('wb') as f:
 plistlib.dump(dict(CFBundleName='观澜选股',CFBundleDisplayName='观澜选股',
  CFBundleIdentifier='local.guanlan.ashare',CFBundleExecutable='Guanlan',
  CFBundlePackageType='APPL',CFBundleShortVersionString='1.8.1',CFBundleVersion='11',
  LSMinimumSystemVersion='14.0',NSHighResolutionCapable=True,
  NSHumanReadableCopyright='本地 A 股研究工具',
  NSAppTransportSecurity={'NSExceptionDomains':{'106.14.125.189':{
   'NSExceptionAllowsInsecureHTTPLoads':True,'NSExceptionMinimumTLSVersion':'TLSv1.2',
   'NSExceptionRequiresForwardSecrecy':True}}}),f)
(app/'Resources'/'runtime.json').write_text(json.dumps(dict(project_root=str(root),python=str(root/'.venv/bin/python'))))
PY
codesign --force --deep --sign - "$GUANLAN_APP_DIR"
printf '已构建：%s\n' "$GUANLAN_APP_DIR"
