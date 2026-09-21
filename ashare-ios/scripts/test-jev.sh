#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p .cache
swiftc -parse-as-library -target arm64-apple-macosx14.0 ../ashare-mac/macos/Models.swift \
  ../ashare-mac/macos/ChartData.swift ../ashare-mac/macos/DailyModels.swift \
  ../ashare-mac/macos/RealtimeModels.swift Tests/JevTests.swift -o .cache/jev-native-tests
.cache/jev-native-tests
