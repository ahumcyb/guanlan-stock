#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
export DEVELOPER_DIR="${DEVELOPER_DIR:-/Applications/Xcode.app/Contents/Developer}"
case "${1:-simulator}" in
  simulator) GUANLAN_SDK=iphonesimulator; GUANLAN_DESTINATION='generic/platform=iOS Simulator'; GUANLAN_SIGNING=(CODE_SIGNING_ALLOWED=YES CODE_SIGN_IDENTITY=-) ;;
  device) GUANLAN_SDK=iphoneos; GUANLAN_DESTINATION='generic/platform=iOS'; GUANLAN_SIGNING=(CODE_SIGNING_ALLOWED=NO) ;;
  *) printf '用法：bash scripts/build-ios.sh [simulator|device]\n' >&2; exit 2 ;;
esac
xcodebuild -quiet -project Guanlan.xcodeproj -scheme Guanlan -configuration Debug \
  -sdk "$GUANLAN_SDK" -destination "$GUANLAN_DESTINATION" -derivedDataPath build/DerivedData "${GUANLAN_SIGNING[@]}" build
printf '编译完成：build/DerivedData/Build/Products/Debug-%s/Guanlan.app\n' "$GUANLAN_SDK"
