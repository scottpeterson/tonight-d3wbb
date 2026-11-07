#!/bin/bash
# Start the site's update runs on GitHub Actions from the Mac. launchd runs this every 20 minutes
# (com.scottpeterson.tonight-d3wbb-finals). GitHub's own cron starts hours late or not at all on busy days
# (the 6 a.m. Eastern run never started on 2026-11-07), and a dispatched run starts within seconds.
#
# - A full run (slates for today and tomorrow) once in each of the workflow's daily hours: 11, 17, and 21 UTC,
#   plus 7 UTC from November to March. A marker file keeps it to one per hour.
# - A finals pass every 20 minutes from 23:00 to 05:59 UTC, November to March, the game-night window.
# Skips when an update run is already queued or running: the workflow takes one run at a time.
set -u
GH=/opt/homebrew/bin/gh
REPO=scottpeterson/tonight-d3wbb
MARK="$(dirname "$0")/../logs/last_full_dispatch"
hour=$((10#$(date -u +%H)))
month=$((10#$(date -u +%m)))
season=0
case $month in 11|12|1|2|3) season=1 ;; esac

mode=""
slot="$(date -u +%F-%H)"
case $hour in
  11|17|21) mode=full ;;
  7) [ $season = 1 ] && mode=full ;;
esac
if [ "$mode" = full ] && [ -f "$MARK" ] && [ "$(cat "$MARK")" = "$slot" ]; then mode=""; fi
if [ -z "$mode" ] && [ $season = 1 ] && { [ "$hour" -ge 23 ] || [ "$hour" -le 5 ]; }; then mode=finals; fi
[ -z "$mode" ] && exit 0

busy=$("$GH" run list -R "$REPO" --workflow update.yml --limit 5 --json status \
  -q '[.[] | select(.status == "queued" or .status == "in_progress" or .status == "pending")] | length')
if [ "${busy:-0}" -gt 0 ]; then
  echo "$(date -u '+%F %T') skipped a $mode run: a run is already queued or running"
  exit 0
fi
if "$GH" workflow run update.yml -R "$REPO" -f mode=$mode; then
  echo "$(date -u '+%F %T') dispatched a $mode run"
  [ "$mode" = full ] && echo "$slot" > "$MARK"
fi
