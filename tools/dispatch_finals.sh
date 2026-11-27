#!/bin/bash
# Start the site's update runs on GitHub Actions from the Mac. launchd runs this every 5 minutes
# (com.scottpeterson.tonight-d3wbb-finals). On busy days GitHub's own cron starts hours late or not at all.
# The 6 a.m. Eastern run never started on 2026-11-07. A dispatched run starts within seconds.
#
# - A full run (slates for today and tomorrow) once in each of the workflow's daily hours. The hours are 11, 17,
#   and 21 UTC, plus 7 UTC from November to March. A marker file keeps it to one per hour.
# - A finals pass every 5 minutes from 23:00 to 05:59 UTC, November to March. That is the game-night window.
# - A finals pass at other times while a game in the live slates is 30 minutes to 4 hours past tipoff without a
#   final. Saturday afternoon tournaments need it (2026-11-07).
# - Before each run, the runner clone (~/projects/tonight-d3wbb-runner) reads the Presto pages that Presto's
#   CloudFront refuses to GitHub's runners (`fetch_data.py --presto`). Then it pushes data/presto_cache.json.
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

# Exit 0 when a game in today's or yesterday's live slate (Eastern dates) tipped off 30 minutes to 4 hours ago.
# The game must also lack a final and a postponement.
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

# The workflow takes one run at a time. A queued run runs git checkout when it starts, so it already gets the
# cache pushed below. Only then is a new dispatch redundant. A run in progress does not block the Presto reads or
# the dispatch. Until 2026-11-24 it skipped the whole cycle. Presto scores then reached the site 29 minutes old.
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

# The Mac's copy of the Presto pages that Presto's CloudFront refuses to GitHub's runners. With two passes, no game
# in progress goes more than 18 minutes between updates (Scott, 2026-11-24).
#
# - The live pass reads only the box scores of games under way (up to 20 requests, about 3 minutes). It pushes and
#   dispatches the run at once.
# - The full pass then reads the schedule pages (up to 20 requests, 3.5 minutes). It pushes for the next run.
#
# The worst case for a live game is about 17.5 minutes. That is 3 minutes of live pass, 3.5 of full pass, and 5 to
# the next start. Then come 3 more of live pass and about 3 for the run and the Pages deploy. A cycle without the
# full pass takes about 14.
#
# launchd starts this every 5 minutes, but it counts the interval from the end of the last run. So a run that took
# 8.5 minutes made an 18.5-minute cycle (2026-11-24). The full pass therefore runs only when the last one ended at
# least 15 minutes ago. The lock directory skips a start while a run is still going.
LOCK="$(dirname "$0")/../logs/dispatch.lock"
FULL_MARK="$(dirname "$0")/../logs/last_presto_full"
if ! mkdir "$LOCK" 2>/dev/null; then
  if [ -n "$(find "$LOCK" -maxdepth 0 -mmin +30)" ]; then rmdir "$LOCK"; mkdir "$LOCK"; else exit 0; fi
fi
trap 'rmdir "$LOCK"' EXIT
if [ -d "$RUNNER/.git" ]; then
  FULL_MARK="$(cd "$(dirname "$FULL_MARK")" && pwd)/$(basename "$FULL_MARK")"
  cd "$RUNNER" || exit 1
  git pull -q --rebase origin main || { echo "$(date -u '+%F %T') runner clone: pull failed"; exit 1; }
  "$UV" run --quiet --with beautifulsoup4 python3 fetch_data.py --presto-live 2>&1 | tail -3
  push_cache " (live)"
  dispatch
  last_full=$(cat "$FULL_MARK" 2>/dev/null || echo 0)
  if [ $(( $(date +%s) - last_full )) -ge 900 ]; then
    "$UV" run --quiet --with beautifulsoup4 python3 fetch_data.py --presto 2>&1 | tail -3
    push_cache ""
    date +%s > "$FULL_MARK"
  fi
else
  dispatch
fi
exit 0
