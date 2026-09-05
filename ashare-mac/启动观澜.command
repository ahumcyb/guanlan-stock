#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -x build/观澜选股.app/Contents/MacOS/Guanlan ]; then
  bash scripts/setup.sh
  bash scripts/build.sh
fi
open build/观澜选股.app
