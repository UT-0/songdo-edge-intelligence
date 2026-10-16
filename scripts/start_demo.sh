#!/usr/bin/env bash
# Start the whole edge node (supervisor + all workers). Ctrl+C stops it cleanly.
set -euo pipefail
cd "$(dirname "$0")/.."
PY=python3
[ -x .venv/bin/python ] && PY=.venv/bin/python
echo "Dashboard: http://127.0.0.1:8000   (Ctrl+C to stop)"
PYTHONPATH=src exec "$PY" -m edge.supervisor --config config/node.yaml "$@"
