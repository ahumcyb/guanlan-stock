#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p .cache
swiftc -parse-as-library -target arm64-apple-macosx14.0 \
  Sources/Core/TonghuashunLink.swift Tests/TonghuashunLinkTests.swift -o .cache/tonghuashun-link-tests
.cache/tonghuashun-link-tests
swiftc -parse-as-library -target arm64-apple-macosx14.0 \
  ../ashare-mac/macos/Models.swift ../ashare-mac/macos/ChartData.swift Sources/Core/Connection.swift Sources/Core/Snapshots.swift Tests/CoreTests.swift -o .cache/core-tests
if [ -n "${2:-}" ]; then
  .cache/core-tests "${1:-../ashare-mac/.cache/mobile-bootstrap/mobile/current}" "$2"
else
  .cache/core-tests "${1:-../ashare-mac/.cache/mobile-bootstrap/mobile/current}"
fi
(cd ../ashare-mac && .venv/bin/python -m unittest discover -s tests -q)
