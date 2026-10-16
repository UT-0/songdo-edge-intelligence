#!/usr/bin/env bash
# Safe online backup. flock -n prevents overlapping runs (cron / systemd timer).
set -euo pipefail
cd "$(dirname "$0")/.."
PY=python3
[ -x .venv/bin/python ] && PY=.venv/bin/python
exec 9>/tmp/songdo_backup.lock
flock -n 9 || { echo "backup already running, skipping"; exit 0; }
PYTHONPATH=src "$PY" - <<'PY'
import time
from edge.core.config import load_config
from edge.core.storage import Storage
cfg = load_config("config/node.yaml")
s = Storage(cfg["paths"]["db"], cfg["paths"]["schema"])
dest = f'{cfg["paths"]["backups"]}/songdo_edge_{time.strftime("%Y%m%d_%H%M%S")}.db'
print("backup", dest, "OK" if s.backup(dest) else "INTEGRITY FAILED")
PY
