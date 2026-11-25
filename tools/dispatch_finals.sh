#!/bin/bash
# Start the site's update runs on GitHub Actions from the Mac. launchd runs this every 10 minutes
# (com.scottpeterson.tonight-d3wbb-finals). GitHub's own cron starts hours late or not at all on busy days
# (the 6 a.m. Eastern run never started on 2026-11-07), and a dispatched run starts within seconds.
#
# - A full run (slates for today and tomorrow) once in each of the workflow's daily hours: 11, 17, and 21 UTC,
#   plus 7 UTC from November to March. A marker file keeps it to one per hour.
# - A finals pass every 10 minutes from 23:00 to 05:59 UTC, November to March, the game-night window, and at any
#   other time while a game in the live slates tipped off 30 minutes to 4 hours ago and has no final yet
#   (Saturday afternoon tournaments, 2026-11-07).
# - Before each run, the runner clone (~/projects/tonight-d3wbb-runner) reads the Presto pages that Presto's
#   CloudFront refuses GitHub's runners (`fetch_data.py --presto`) and pushes data/presto_cache.json.
set -u
GH=/opt/homebrew/bin/gh
UV=/Users/scottpeterson/.local/bin/uv
REPO=scottpeterson/tonight-d3wbb
RUNNER=/Users/scottpeterson/projects/tonight-d3wbb-runner
MARK="$(dirname "$0")/../logs/last_full_dispatch"
hour=$((10#$(date -u +%H)))
month=$((10#$(date -u +%m)))
season=0
case $month in 11|12|1|2|3) season=1 ;; esac

# 0 when a game in today's or yesterday's live slate (Eastern dates) tipped off 30 minutes to 4 hours ago
# with no final and no postponement.
games_pending() {
  /usr/bin/python3 - <<'PY'
import datetime, json, sys, urllib.request
from zoneinfo import ZoneInfo
now = datetime.datetime.now(datetime.timezone.utc)
today = now.astimezone(ZoneInfo("America/New_York")).date()
for day in (today, today - datetime.timedelta(days=1)):
    try:
        with urllib.request.urlopen(f"https://www.tonightind3wbb.com/slates/{day}.json?t={int(now.timestamp())}", timeout=20) as r:
            games = json.load(r)["games"]
    except Exception:
        continue
    for g in games:
        if g.get("final") or g.get("off") or not g.get("tip"):
            continue
        age = now - datetime.datetime.fromisoformat(g["tip"].replace("Z", "+00:00"))
        if datetime.timedelta(minutes=30) <= age <= datetime.timedelta(hours=4):
            sys.exit(0)
sys.exit(1)
PY
}

mode=""
slot="$(date -u +%F-%H)"
case $hour in
  11|17|21) mode=full ;;
  7) [ $season = 1 ] && mode=full ;;
esac
if [ "$mode" = full ] && [ -f "$MARK" ] && [ "$(cat "$MARK")" = "$slot" ]; then mode=""; fi
if [ -z "$mode" ] && [ $season = 1 ]; then
  if [ "$hour" -ge 23 ] || [ "$hour" -le 5 ] || games_pending; then mode=finals; fi
fi
[ -z "$mode" ] && exit 0

# The workflow takes one run at a time. A queued run checks out the repo when it starts, so it already gets the
# cache pushed below; only then is a new dispatch redundant. A run in progress does not block the Presto reads or
# the dispatch: until 2026-11-24 it skipped the whole cycle, and Presto scores reached the site 29 minutes old.
queued() {
  n=$("$GH" run list -R "$REPO" --workflow update.yml --limit 5 --json status \
    -q '[.[] | select(.status == "queued" or .status == "pending" or .status == "waiting")] | length')
  [ "${n:-0}" -gt 0 ]
}

dispatch() {
  if queued; then
    echo "$(date -u '+%F %T') skipped a $mode dispatch: a run is already queued and gets the new cache"
  elif "$GH" workflow run update.yml -R "$REPO" -f mode=$mode; then
    echo "$(date -u '+%F %T') dispatched a $mode run"
    [ "$mode" = full ] && echo "$slot" > "$MARK"
  fi
}

# Push the runner clone's Presto cache when it changed.
push_cache() {
  if [ -n "$(git status --porcelain data/presto_cache.json)" ]; then
    git add data/presto_cache.json
    git commit -q -m "Presto cache $(date -u '+%F %H:%M UTC')$1"
    git pull -q --rebase origin main && git push -q origin HEAD:main && echo "$(date -u '+%F %T') pushed the Presto cache$1"
  fi
}

# The Mac's copy of the Presto pages that Presto's CloudFront refuses GitHub's runners. Two passes, so no game in
# progress goes more than 18 minutes between updates (Scott, 2026-11-24): the live pass reads only the box scores
# of games under way (up to 20 requests, about 3 minutes), pushes, and dispatches the run at once; the full pass
# then reads the schedule pages (up to 30 requests, 5 minutes) and pushes for the next run. Worst case for a live
# game: 10 minutes to the next cycle, 3 for the live pass, about 3 for the run and the Pages deploy.
if [ -d "$RUNNER/.git" ]; then
  cd "$RUNNER" || exit 1
  git pull -q --rebase origin main || { echo "$(date -u '+%F %T') runner clone: pull failed"; exit 1; }
  "$UV" run --quiet --with beautifulsoup4 python3 fetch_data.py --presto-live 2>&1 | tail -3
  push_cache " (live)"
  dispatch
  "$UV" run --quiet --with beautifulsoup4 python3 fetch_data.py --presto 2>&1 | tail -3
  push_cache ""
else
  dispatch
fi
exit 0
