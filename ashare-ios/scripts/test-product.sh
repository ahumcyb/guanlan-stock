#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p .cache
GUANLAN_FIXTURE="${1:-../ashare-mac/.cache/left-settlement-publication/mobile/current}"
swiftc -parse-as-library -target arm64-apple-macosx14.0 \
  ../ashare-mac/macos/Models.swift ../ashare-mac/macos/ChartData.swift Sources/Core/Connection.swift Sources/Core/Snapshots.swift Tests/CoreTests.swift -o .cache/product-core-tests
.cache/product-core-tests "$GUANLAN_FIXTURE"
swiftc -parse-as-library -target arm64-apple-macosx14.0 \
  ../ashare-mac/macos/Models.swift ../ashare-mac/macos/ChartData.swift Sources/Core/Connection.swift Sources/Core/Snapshots.swift Sources/Core/Watchlist.swift Tests/WatchlistTests.swift -o .cache/product-watchlist-tests
.cache/product-watchlist-tests
swiftc -parse-as-library -target arm64-apple-macosx14.0 \
  ../ashare-mac/macos/Models.swift ../ashare-mac/macos/ChartData.swift ../ashare-mac/macos/DailyModels.swift ../ashare-mac/macos/RealtimeModels.swift Tests/NotificationTests.swift -o .cache/product-notification-tests
.cache/product-notification-tests
swiftc -parse-as-library -target arm64-apple-macosx14.0 \
  ../ashare-mac/macos/Models.swift ../ashare-mac/macos/ChartData.swift ../ashare-mac/macos/DailyModels.swift ../ashare-mac/macos/RealtimeModels.swift \
  Sources/Core/Connection.swift Sources/Core/Snapshots.swift Sources/Core/Watchlist.swift Sources/Core/MobileStore.swift \
  Tests/NotificationRaceTests.swift -o .cache/notification-race-tests
.cache/notification-race-tests
bash scripts/test-daily.sh

bash scripts/test-chart.sh
