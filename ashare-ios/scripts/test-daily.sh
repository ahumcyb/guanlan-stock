#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p .cache
if [ -z "${1:-}" ]; then
  (cd ../ashare-mac && .venv/bin/python -m tests.generate_daily_fixture --output ../ashare-ios/.cache/daily-native-fixture.json)
fi
swiftc -parse-as-library -target arm64-apple-macosx14.0 \
  ../ashare-mac/macos/Models.swift ../ashare-mac/macos/DailyModels.swift Tests/DailyTests.swift -o .cache/daily-tests
.cache/daily-tests "${1:-.cache/daily-native-fixture.json}"
