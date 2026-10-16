#!/usr/bin/env bash
# Preflight audit: kernel, shell, Python, SQLite, required POSIX tools.
fail=0
ok()   { echo "[ OK ] $1"; }
bad()  { echo "[FAIL] $1"; fail=1; }
warn() { echo "[WARN] $1"; }

echo "Kernel: $(uname -sr)"
echo "Shell : ${BASH_VERSION:+bash $BASH_VERSION}"

if command -v python3 >/dev/null; then
  ver=$(python3 -c 'import sys;print("%d.%d"%sys.version_info[:2])')
  if python3 -c 'import sys;sys.exit(0 if sys.version_info>=(3,12) else 1)'; then ok "Python $ver"
  else warn "Python $ver (project targets 3.12)"; fi
  python3 -c 'import sqlite3;print("[ OK ] SQLite", sqlite3.sqlite_version)' || bad "sqlite3 module"
else
  bad "python3 not found"
fi

for t in ps pkill awk sed flock curl; do
  command -v "$t" >/dev/null && ok "$t" || bad "$t missing"
done
exit $fail
