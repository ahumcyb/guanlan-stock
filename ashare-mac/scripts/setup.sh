#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -x .venv/bin/python ]; then
  if command -v uv >/dev/null 2>&1; then
    uv venv --no-project .venv --python /usr/bin/python3
  else
    /usr/bin/python3 -m venv .venv
  fi
fi
if command -v uv >/dev/null 2>&1; then
  uv pip install --python .venv/bin/python -r requirements.txt
else
  .venv/bin/python -m pip install -r requirements.txt
fi
.venv/bin/python -c 'import pandas,numpy,pyarrow; print("研究环境就绪")'
