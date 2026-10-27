#!/bin/bash
# Entry point for launchd on the Mac.
# With a GitHub remote, the Actions workflow fetches, builds, and commits, so this
# job only pulls the latest build. Without a remote, it fetches and builds here.
set -u
cd "$(dirname "$0")" || exit 1
PY=/opt/homebrew/bin/python3
mkdir -p logs
if git rev-parse --is-inside-work-tree >/dev/null 2>&1 && git remote get-url origin >/dev/null 2>&1; then
  git pull -q --rebase origin main || { git rebase --abort 2>/dev/null; echo "[$(date '+%F %T')] pull failed; keeping local state"; }
else
  $PY fetch_data.py
  $PY build_site.py
fi
