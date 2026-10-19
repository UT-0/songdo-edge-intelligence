#!/usr/bin/env bash
# Safe online backup (SQLite online backup API) with flock overlap prevention.
#   bash scripts/backup.sh [config]        default config: config/node.yaml  (e.g. config/os4.yaml)
# Scheduled by systemd (songdo-backup@.timer) or cron; overlapping runs are skipped, not queued.
#
# NOTE: this script's own lock file is /tmp/songdo_backup_<config name>.lock. It must NOT be
# /tmp/songdo_backup.lock, which the handbook example uses OUTSIDE the script:
#   flock -n /tmp/songdo_backup.lock -c "./scripts/backup.sh"
# With the same file, the inner flock would always fail and no backup would ever run.
set -euo pipefail
cd "$(dirname "$0")/.."
CONFIG="${1:-config/node.yaml}"
PY=python3
[ -x .venv/bin/python ] && PY=.venv/bin/python
exec 9>"/tmp/songdo_backup_$(basename "$CONFIG" .yaml).lock"
flock -n 9 || { echo "backup already running, skipping"; exit 0; }
sleep "${BACKUP_TEST_HOLD_S:-0}"      # test hook: keep the lock for N seconds (default 0)
PYTHONPATH=src exec "$PY" -m edge.teams.os4_iot.s4_scheduled_backup --config "$CONFIG" --once
