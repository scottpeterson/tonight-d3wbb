#!/bin/bash
# Start a game-night finals pass on GitHub Actions. launchd runs this every 20 minutes
# (com.scottpeterson.tonight-d3wbb-finals). GitHub's own cron for these runs can start hours late,
# and a dispatched run starts within seconds.
#
# Runs only from 23:00 to 05:59 UTC, November to March, the same window as the workflow's game-night cron.
# Skips when an update run is already queued or running: the workflow takes one run at a time.
set -u
GH=/opt/homebrew/bin/gh
REPO=scottpeterson/tonight-d3wbb
hour=$((10#$(date -u +%H)))
month=$((10#$(date -u +%m)))

case $month in 11|12|1|2|3) ;; *) exit 0 ;; esac
if [ "$hour" -lt 23 ] && [ "$hour" -gt 5 ]; then exit 0; fi

busy=$("$GH" run list -R "$REPO" --workflow update.yml --limit 5 --json status \
  -q '[.[] | select(.status == "queued" or .status == "in_progress" or .status == "pending")] | length')
if [ "${busy:-0}" -gt 0 ]; then
  echo "$(date -u '+%F %T') skipped: a run is already queued or running"
  exit 0
fi
"$GH" workflow run update.yml -R "$REPO" -f mode=finals && echo "$(date -u '+%F %T') dispatched a finals pass"
