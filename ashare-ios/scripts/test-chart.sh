#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p .cache
swiftc -parse-as-library -target arm64-apple-macosx14.0 \
  ../ashare-mac/macos/Models.swift ../ashare-mac/macos/ChartData.swift ../ashare-mac/macos/ChartMath.swift \
  Tests/ChartTests.swift -o .cache/chart-tests
.cache/chart-tests
swiftc -parse-as-library -target arm64-apple-macosx14.0 \
  ../ashare-mac/macos/Models.swift ../ashare-mac/macos/ChartData.swift ../ashare-mac/macos/ChartLoadState.swift \
  Tests/ChartLoadTests.swift -o .cache/chart-load-tests
.cache/chart-load-tests
swiftc -parse-as-library -target arm64-apple-macosx14.0 \
  ../ashare-mac/macos/Models.swift ../ashare-mac/macos/ChartData.swift Sources/Core/Connection.swift Sources/Core/Snapshots.swift \
  Tests/ChartCacheTests.swift -o .cache/chart-cache-tests
.cache/chart-cache-tests
