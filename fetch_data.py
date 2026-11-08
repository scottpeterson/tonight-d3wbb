#!/usr/bin/env python3
"""Build each night's slate of NPI games into data/slates/YYYY-MM-DD.json.

Rules this file enforces for every project built from the html-report template:

- One summary file, data/data.json, with `fetched_at`, `errors`, and `stale`.
  The builder reads it and the slate files, so a fetch failure can never blank the page.
- A source that fails keeps its last good value (carry forward).
- Exit 1 when any source failed, after writing the files, so the workflow log
  shows it while the site still builds.

Each run does three things:

1. Reads The D3 Stat Lab's gameLeverages.json (every scheduled game between two
   teams that count for the NPI, with season efficiency ranks, pregame win probability,
   and leverage), seasonSimulations.json (tournament chance), and newcomers.json.
2. For today and tomorrow (Eastern), reads every D3 team's schedule page to find
   tipoff and the live stats feed, and writes the slate. A page row against another
   D3 team that gameLeverages.json lacks becomes a game too, with no win chance or
   leverage until the next NPI update: a tournament's second-day game shows as TBA
   on the pages until the first day ends. Games against Division I and II teams,
   exhibitions, and games against NAIA and two-year schools do not appear.
3. For the last three days, reads each game that has no box score yet. With
   --finals (the game-night run every 20 minutes), the run does only this step
   and reads only the schedule pages those games need. The live
   feed comes first. Once a game is 2.5 hours past tipoff and its feed has no
   complete box score (crews reuse a feed for their next game), the fetcher reads
   the Box Score link on either team's schedule page instead: Sidearm HTML or
   Presto StatCrew XML. It stores the final score, the line of every newcomer
   who played, and the game's 15 best lines by any player. A score a schedule
   page posts outranks the feed's. A game with no feed the browser can read but
   a Presto box score page gets a snapshot of its score and period while it is
   on; the page shows it with the time it was read. The page shows the night's top 15 game scores
   from each list.

4. `python fetch_data.py --presto`, on the Mac before each dispatched run: Presto's
   CloudFront answers 405 to every GitHub runner, so the Mac reads every Presto
   school's schedule page and the Presto box score page of every game still
   without one, and writes data/presto_cache.json. The runner falls back to that
   copy when a Presto page refuses it.
"""
import csv
import html
import http.client
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
SLATES = DATA / "slates"
OUT = DATA / "data.json"
EXTRA = DATA / "extra_games.json"
# The Mac's copy of what Presto sites refuse the runner; tools/dispatch_finals.sh runs `fetch_data.py --presto` to write it.
PRESTO_CACHE = DATA / "presto_cache.json"
PRESTO_CACHE_LIVE = timedelta(hours=2)
PRESTO_PACE = 10  # seconds between Presto requests: about six a minute from one address trip the WAF challenge
PRESTO_BUDGET = 45  # Presto requests per Mac run, so a run ends inside the dispatcher's 20-minute cycle  # a cached in-progress box score older than this is no snapshot
MEMBERS = DATA / "ncaa_members.csv"
SITE = json.loads((BASE / "site.json").read_text())
# The bare domain: ESPN answers 403 to this user agent when it names www.tonightind3wbb.com.
UA = {"User-Agent": f"Mozilla/5.0 ({re.sub(r'^www\.', '', SITE.get('domain') or SITE['slug'])} page builder)",
      "Accept": "text/html,application/json;q=0.9,*/*;q=0.8", "Accept-Language": "en-US,en;q=0.9"}
TAG = re.compile(r"<[^>]+>")
# HTTPException covers a body cut off partway (IncompleteRead) and a dropped connection; OSError covers resets.
FETCH_ERRORS = (urllib.error.URLError, http.client.HTTPException, OSError, TimeoutError, ValueError, KeyError, IndexError,
                ET.ParseError)
EASTERN = ZoneInfo("America/New_York")
STATLAB = "https://thed3statlab.com/data"
# Testing aids: read The D3 Stat Lab files from a local checkout, and pretend today is another date.
STATLAB_DIR = os.environ.get("TONIGHT_STATLAB_DIR")
TODAY = os.environ.get("TONIGHT_TODAY")
ZONES = {"ET": "America/New_York", "EST": "America/New_York", "EDT": "America/New_York",
         "CT": "America/Chicago", "CST": "America/Chicago", "CDT": "America/Chicago",
         "MT": "America/Denver", "MST": "America/Denver", "MDT": "America/Denver",
         "PT": "America/Los_Angeles", "PST": "America/Los_Angeles", "PDT": "America/Los_Angeles"}
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
SEASON_START_YEAR = 2026
SLATE_DAYS_AHEAD = 1  # today and tomorrow
FINALS_DAYS_BACK = 3  # schools post a box score link hours or a day late
BOX_PAGE_AFTER = timedelta(hours=2, minutes=30)  # a game this long past tipoff is over; its box score page is the record
FINAL_EARLIEST = timedelta(minutes=45)  # no game ends sooner after tipoff, so a final before that is not this game's


def now():
    return datetime.now(timezone.utc)


WAF_CHALLENGE = re.compile(rb"awswaf|challenge\.js|gokuProps", re.I)


def waf_challenged(resp, body):
    """True when AWS WAF answered with its JavaScript challenge instead of the page (Presto's CloudFront, after
    about six requests a minute from one address): status 202, an x-amzn-waf-action header, or a short page that
    loads the challenge script."""
    return resp.status == 202 or bool(resp.headers.get("x-amzn-waf-action")) or (len(body) < 5000 and bool(WAF_CHALLENGE.search(body)))


def get(url, as_json=False, timeout=30):
    """GET a URL with a browser-like user agent. Raises on HTTP and network errors, and on a WAF challenge page."""
    req = urllib.request.Request(url, headers=UA)
    for attempt in (1, 2):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read()
                if waf_challenged(resp, body):
                    raise http.client.HTTPException(f"WAF challenge from {site_of(url)}")
            break
        except (TimeoutError, urllib.error.URLError) as exc:
            # One retry for a timeout; HTTP errors (404, 500) are answers, not hiccups.
            if attempt == 2 or isinstance(exc, urllib.error.HTTPError):
                raise
    text = body.decode("utf-8", "replace")
    return json.loads(text) if as_json else text


def text(fragment):
    return re.sub(r"\s+", " ", html.unescape(TAG.sub(" ", fragment or ""))).strip()


def absolute(url, base):
    return urllib.parse.urljoin(base, html.unescape(url.strip())) if url else None


def name_tokens(name):
    return set(re.findall(r"[a-z]+", (name or "").lower())) - {"university", "college", "of", "the", "at", "vs", "state"}


def code_hit(code, team):
    """True when a feed's team code names the team: a word of it (MEDGAR), its initials (SJLI), or its start."""
    c = re.sub(r"[^a-z]", "", (code or "").lower())
    t = re.sub(r"[^a-z]", "", (team or "").lower())
    initials = "".join(w[0] for w in re.findall(r"[a-z]+", re.sub(r"['\u2019]", "", (team or "").lower())))
    return len(c) >= 2 and (c in name_tokens(team) or c == initials or (len(c) >= 4 and t.startswith(c)))


GENERIC_WORDS = {"university", "college", "of", "the", "at", "vs", "state", "st", "saint", "s", "institute", "inst"}
MIN_ROSTER = 5  # a shorter roster list is a team whose roster is not published yet


def name_words(name):
    """Distinctive words of a team name: "St. Joseph's (LI)" -> {'josephs', 'li'}."""
    return set(re.findall(r"[a-z]+", re.sub(r"['\u2019]", "", (name or "").lower()))) - GENERIC_WORDS


def line_last(line):
    """A box line's last name, letters only: from 'last', else 'Last, First', else 'F. Last'."""
    abbr = (line.get("abbr") or "").strip()
    last = (line.get("last") or "").strip() or (abbr.split(",")[0] if "," in abbr else (abbr.split() or [""])[-1])
    return norm(last)


def roster_of(game, t):
    roster = game.get(t + "_roster") or []
    return roster if len(roster) >= MIN_ROSTER else None


def roster_hits(lines, roster):
    last = {norm(n.split()[-1]) for n in roster or [] if n.split()}
    return sum(1 for line in lines if line_last(line) in last)


def names_team(side, game, t):
    """True when a feed side's code or typed name matches any name a source uses for the team."""
    words = name_words(side.get("name"))
    for name in game.get(t + "_names") or [game[t]]:
        theirs = name_words(name)
        if code_hit(side.get("id"), name) or (words and theirs and (words <= theirs or theirs <= words)):
            return True
    return False


def feed_is_game(game, sides, lines):
    """False when the feed shows another game. A host's crew can run one feed for every game of its tournament
    (St. Joseph's Brooklyn, 2026-11-06: Pratt's game, then Medgar Evers vs St. Joseph's Long Island). Players
    decide first: two of our teams' players in the box score make it ours, none make it someone else's. Without
    them, one feed side has to match one of our teams by name or code."""
    known = [t for t in ("home", "away") if roster_of(game, t)]
    if known and sum(len(lines.get(k, [])) for k in "HV") >= MIN_ROSTER:
        hits = {t: sum(roster_hits(lines.get(k, []), roster_of(game, t)) for k in "HV") for t in known}
        if sum(hits.values()) == 0:
            return False
        # Both rosters known and both sides listed: a team with no player in the box score is not playing. Principia's
        # tournament feed (2026-11-07) showed Aurora vs Westminster, and Aurora's players alone must not make it the
        # phantom Aurora at Principia.
        if len(known) == 2 and all(lines.get(k) for k in "HV") and min(hits.values()) == 0:
            return False
        if sum(hits.values()) >= 2:
            return True
    if not any(s.get("name") or s.get("id") for s in sides.values()):
        return True
    return any(names_team(sides[k], game, t) for k in "HV" if k in sides for t in ("home", "away"))


def side_fit(side, game, t, lines):
    """Evidence that a feed side is this team: its players most, then its code, then its typed name."""
    roster = roster_of(game, t)
    players = roster_hits(lines, roster) if roster else sum(1 for line in lines if match_newcomer(line, game.get("newcomers_" + t) or []))
    names = game.get(t + "_names") or [game[t]]
    code = any(code_hit(side.get("id"), n) for n in names)
    return 4 * players + 2 * code + (1 if any(name_tokens(side.get("name")) & name_tokens(n) for n in names) else 0)


def should_flip(game, sides, lines):
    """Crews sometimes type team names on the wrong sides (Medgar Evers vs St. Joseph's Long Island,
    2026-11-06), so orient by players and team code before the typed name."""
    def fit(home, away):
        return side_fit(sides["H"], game, home, lines.get("H", [])) + side_fit(sides["V"], game, away, lines.get("V", []))
    return fit("away", "home") > fit("home", "away")


# ---------------------------------------------------------------- inputs

def statlab(name):
    if STATLAB_DIR:
        return json.loads((Path(STATLAB_DIR) / name).read_text())
    return get(f"{STATLAB}/{name}", as_json=True)


def team_names():
    """{team: [every name a source uses]} from data/team_names.csv (tools/make_team_data.py)."""
    path = DATA / "team_names.csv"
    if not path.exists():
        return {}
    with open(path, newline="", encoding="utf-8") as f:
        return {r["team"]: r["names"].split("|") for r in csv.DictReader(f)}


def team_rosters():
    """{team: [player names]} from data/rosters.csv (tools/make_team_data.py)."""
    path, out = DATA / "rosters.csv", {}
    if path.exists():
        with open(path, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                out.setdefault(r["team"], []).append(r["player"])
    return out


def load_schools():
    with open(DATA / "schools.csv", newline="") as f:
        return {r["team"]: r for r in csv.DictReader(f)}


def tournament_chance():
    """Team -> share of simulations that reach the NCAA tournament, 0 to 1."""
    out = {}
    for r in statlab("seasonSimulations.json"):
        raw = str(r.get("Tourn%") or "0").rstrip("%")
        out[r["Team"]] = float(raw) / 100 if raw not in ("", "-") else 0.0
    return out


def newcomers_by_team():
    out = {}
    for p in statlab("newcomers.json")["players"]:
        out.setdefault(p["team"], []).append({"name": p["name"], "class": p["class"], "reason": p["reason"]})
    return out


# ---------------------------------------------------------------- schedule pages

def parse_month_day(label):
    m = re.search(r"([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2})", label or "")
    if not m or m.group(1).lower() not in MONTHS:
        return None
    month, day = MONTHS[m.group(1).lower()], int(m.group(2))
    return date(SEASON_START_YEAR if month >= 8 else SEASON_START_YEAR + 1, month, day)


def parse_time(label, home_tz):
    """'7 PM (CT)', '7:30 PM EST', '12 PM' -> (hour, minute, zone). None when the time is TBA."""
    m = re.search(r"(\d{1,2})(?::(\d{2}))?\s*([AP])\.?M\.?(?:\s*\(?([A-Z]{2,3})\)?)?", label or "", re.I)
    if not m:
        return None
    hour = int(m.group(1)) % 12 + (12 if m.group(3).upper() == "P" else 0)
    zone = ZONES.get((m.group(4) or "").upper(), home_tz)
    return hour, int(m.group(2) or 0), zone


def game_blocks(page, start_pattern):
    """Slices of the page, one per game, from each game's opening tag to the next game's."""
    starts = [m.start() for m in re.finditer(start_pattern, page)]
    blocks = []
    for i, a in enumerate(starts):
        b = starts[i + 1] if i + 1 < len(starts) else len(page)
        chunk = page[a:b]
        if i + 1 == len(starts):
            cut = re.search(r"<footer|</section>|<div[^>]*class=\"[^\"]*(?:footer|page-content-body)", chunk)
            if cut:
                chunk = chunk[:cut.start()]
        blocks.append(chunk)
    return blocks


LINK_KEYS = {"live stats": "live_stats", "live stats live stats": "live_stats", "live stats (opens in new window)": "live_stats", "statview": "live_stats",
             "box score": "boxscore", "watch": "video", "video": "video", "watch live": "video", "live video": "video",
             "watch (s)": "video"}


def links_in(block, base):
    links = {}
    for href, label in re.findall(r'<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', block, re.S):
        key = LINK_KEYS.get(text(label).lower())
        if key and key not in links:
            links[key] = absolute(href, base)
    return links


def row(day, time_parts, home, neutral, opponent, links, result_text, note, opponent_url=""):
    return {"day": day, "time": time_parts, "home": home, "neutral": neutral, "opponent": opponent,
            "links": links, "result": result_text, "exhibition": bool(re.search(r"exhib|scrimmage", f"{note} {opponent}", re.I)),
            "opponent_url": opponent_url}


def sidearm_rows(url, tz):
    page = get(url)
    out = []
    for b in game_blocks(page, r'<li[^>]*class="sidearm-schedule-game[\s"]'):
        cls = re.search(r'class="([^"]*)"', b).group(1)
        date_m = re.search(r'sidearm-schedule-game-opponent-date[^>]*>(.*?)</div>', b, re.S)
        spans = [text(s) for s in re.findall(r"<span[^>]*>(.*?)</span>", date_m.group(1), re.S)] if date_m else []
        opp_m = re.search(r'sidearm-schedule-game-opponent-name[^>]*>(.*?)</div>', b, re.S)
        # The class must end there: a postponed game also carries "sidearm-schedule-game-result-final">Final (Hendrix, 2026-11-07).
        result_m = re.search(r'sidearm-schedule-game-result[\s"][^>]*>(.*?)</div>', b, re.S)
        note_m = re.search(r'sidearm-schedule-game-tournament[^>]*>(.*?)</div>', b, re.S)
        # "Exhibition" and "Scrimmage" sometimes sit in the promotion line instead.
        promo_m = re.search(r'sidearm-schedule-game-promotion-name[^>]*>(.*?)</span>', b, re.S)
        day = parse_month_day(spans[0] if spans else "")
        if day:
            out.append(row(day, parse_time(spans[1] if len(spans) > 1 else "", tz), "sidearm-schedule-home-game" in cls,
                           "sidearm-schedule-neutral-game" in cls, text(opp_m.group(1)) if opp_m else "", links_in(b, url),
                           text(result_m.group(1)) if result_m else "", " ".join(text(m.group(1)) for m in (note_m, promo_m) if m),
                           opponent_link(opp_m.group(1)) if opp_m else ""))
    return out or sidearm_table_rows(page, url, tz) or sidearm_card_rows(page, url, tz)


CARD_LINKS = {"live stats": "live_stats", "stats": "live_stats", "watch": "video", "box score": "boxscore"}


def sidearm_card_rows(page, url, tz):
    """Rows of Sidearm's newer layout (many Division I sites): one game card per game, a "vs" or "at" stamp,
    "Oct 28 (Wed) 7:00 PM", the opponent linked as "<name> Website", and Live stats, Stats, and Watch links."""
    soup = BeautifulSoup(page, "html.parser")
    out = []
    for card in soup.select('[data-test-id="s-game-card-standard__root"]'):
        words = " ".join(card.get_text(" ", strip=True).split())
        when = re.search(r"\b([A-Z][a-z]{2})\.? (\d{1,2}) \([A-Za-z]{3}\)\s*(TBA|TBD|\d{1,2}(?::\d{2})?\s*[AP]\.?M\.?(?:\s*[ECMP][SD]?T)?)?", words)
        day = parse_month_day(f"{when.group(1)} {when.group(2)}") if when else None
        team = card.select_one('a[aria-label$="Website"]')
        if not day or not team:
            continue
        stamp = card.select_one(".s-stamp__text")
        links = {}
        for a in card.select("a[href]"):
            key = CARD_LINKS.get(a.get_text(" ", strip=True).lower())
            if key and key not in links:
                links[key] = absolute(a["href"], url)
        result = re.search(r"\b[WLT],?\s*\d{1,3}\s*-\s*\d{1,3}", words)
        out.append(row(day, parse_time(when.group(3) or "", tz), (stamp.get_text(strip=True) if stamp else "") == "vs", False,
                       team.get("title") or team.get_text(" ", strip=True), links, result.group(0) if result else "",
                       "exhibition" if re.search(r"\bexhib", words, re.I) else "", team["href"].strip()))
    return out


def opponent_link(fragment):
    """The opponent's own site, which Sidearm links from the opponent's name."""
    m = re.search(r'href="(https?://[^"]+)"', fragment)
    return m.group(1) if m else ""


def sidearm_table_rows(page, url, tz):
    """Rows of the older Sidearm table layout (conference sites such as gounitedeast.com):
    date as 11/11/2026, opponent with "at " for away and "vs. " for neutral, time as "6:00 P.M."."""
    table = re.search(r'<table[^>]*sidearm-schedule-table.*?</table>', page, re.S)
    out = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", table.group(0) if table else "", re.S):
        cells = [text(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
        m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", cells[0]) if len(cells) >= 3 else None
        if not m:
            continue
        opponent = cells[1]
        away, neutral = opponent.lower().startswith("at "), bool(re.match(r"vs\.?\s", opponent, re.I))
        opponent = re.sub(r"^(?:at|vs\.?)\s+", "", opponent, flags=re.I)
        out.append(row(date(int(m.group(3)), int(m.group(1)), int(m.group(2))), parse_time(cells[2], tz),
                       not away and not neutral, neutral, opponent, links_in(tr, url),
                       cells[2] if re.match(r"[WLT][ ,]", cells[2]) else "", ""))
    return out


ARIA = re.compile(r"event:\s+([A-Z][a-z]+)\s+(\d{1,2})\s+(\d{1,2}):(\d{2})\s*([AP])M", re.I)


def presto_rows(url, tz):
    """Rows of a Presto schedule page. Presto has several templates (cards, tables); every one puts
    "Women's Basketball event: November 14 02:00 PM: ..." in each link's aria-label, so date and
    tipoff come from there. A time printed with a zone in the row (3:00 PM MST) overrides the school's zone."""
    soup = BeautifulSoup(get(url), "html.parser")
    out = []
    for r in soup.select(".event-row"):
        classes = r.get("class") or []
        name = (r.select_one(".event-opponent-name .team-name") or r.select_one(".event-opponent-name")
                or r.select_one(".opponent .team-name") or r.select_one(".team-name"))
        opponent = " ".join(name.get_text(" ", strip=True).split()) if name else ""
        labels = " ".join(a.get("aria-label") or "" for a in r.select("a[aria-label]"))
        m = ARIA.search(labels)
        row_text = " ".join(r.get_text(" ", strip=True).split())
        if m and m.group(1).lower()[:3] in MONTHS:
            month, day_n = MONTHS[m.group(1).lower()[:3]], int(m.group(2))
            day = date(SEASON_START_YEAR if month >= 8 else SEASON_START_YEAR + 1, month, day_n)
            hour = int(m.group(3)) % 12 + (12 if m.group(5).upper() == "P" else 0)
            printed = (hour, int(m.group(4)), tz)
        else:
            # A row with no links has no aria-label. Read the printed date; table templates print
            # only "Sat. 14" under a month heading.
            node = r.select_one(".date") or r.select_one(".event-dateinfo") or r.select_one(".e_date")
            when = " ".join(node.get_text(" ", strip=True).split()) if node else ""
            if not parse_month_day(when):
                heading = r.find_previous(class_="month-title")
                dnum = re.search(r"\b\d{1,2}\b", when)
                when = f"{heading.get_text(' ', strip=True).split()[0]} {dnum.group(0)}" if heading and dnum else ""
            day = parse_month_day(when)
            printed = parse_time(row_text, tz)
        if not opponent or not day:
            continue
        zoned = parse_time(row_text, tz) if re.search(r"\d\s*[AP]\.?M\.?\s*\(?[ECMP][SD]?T\b", row_text) else None
        time_parts = zoned or (None if re.search(r"\bTBA\b|\bTBD\b", row_text) else printed)
        result = r.select_one(".event-result") or r.select_one(".e_result")
        out.append(row(day, time_parts, "home" in classes and "neutral" not in classes, "neutral" in classes, opponent,
                       links_in(str(r), url), result.get_text(" ", strip=True) if result else "",
                       "exhibition" if "exhibition" in classes or "Scrimmage" in row_text else ""))
    seen, unique = set(), []
    for x in out:  # Presto repeats the next game in a banner card
        key = (x["day"], x["opponent"])
        if key not in seen:
            seen.add(key)
            unique.append(x)
    return unique


def season_url(url):
    """Presto paths name the season; point them at 2026-27."""
    label = f"{SEASON_START_YEAR}-{str(SEASON_START_YEAR + 1)[2:]}"
    return re.sub(r"/\d{4}-\d{2}(?=/|$)", f"/{label}", url)


def schedule_rows(school, fallback=True):
    if not school or not school.get("schedule"):
        return []
    presto = school["type"] == "Presto"
    reader, url = (presto_rows, season_url(school["schedule"])) if presto else (sidearm_rows, school["schedule"])
    try:
        # Some sites now and then serve a page with no games and a 200; one more read fixes it.
        rows = reader(url, school["tz"]) or reader(url, school["tz"])
    except FETCH_ERRORS:
        # Presto's CloudFront answers 405 to every GitHub runner (schedule and box score pages alike, 2026-11-07),
        # and answers the Mac, so the Mac's copy stands in.
        rows = cached_rows(school["team"]) if presto and fallback else None
        if rows is None:
            raise
    return rows or (cached_rows(school["team"]) if presto and fallback else None) or []


# ---------------------------------------------------------------- the Mac's Presto cache

_presto_cache = None


def presto_cache():
    global _presto_cache
    if _presto_cache is None:
        _presto_cache = read_json(PRESTO_CACHE, {}) or {}
    return _presto_cache


def row_to_json(r):
    return {**r, "day": r["day"].isoformat()}


def row_from_json(d):
    return {**d, "day": date.fromisoformat(d["day"]), "time": tuple(d["time"]) if d["time"] else None}


def cached_rows(team):
    rows = presto_cache().get("pages", {}).get(team)
    return [row_from_json(r) for r in rows] if rows else None


def cached_box(url):
    """A box score page the Mac read: a final at any age, a score in progress only while it is fresh."""
    entry = presto_cache().get("boxes", {}).get(url)
    if not entry:
        return None
    if not entry["box"]["complete"] and now() - datetime.fromisoformat(entry["at"]) > PRESTO_CACHE_LIVE:
        return None
    return entry["box"]


def presto_snapshot(previous=None):
    """The Mac's run (`fetch_data.py --presto`): read Presto pages one at a time, PRESTO_PACE seconds apart, and
    write data/presto_cache.json for the runner, which Presto's CloudFront refuses. Order: the schedule pages of
    Presto schools with a game in the finals window, the box score page of every such game still without one, then
    the other Presto schools, up to PRESTO_BUDGET requests. A page that fails or comes back empty keeps its last
    copy. Twelve parallel reads tripped the WAF challenge on every box score page (2026-11-08)."""
    out = {"fetched_at": now().isoformat(timespec="seconds"), "errors": []}
    schools = load_schools()
    extra = read_json(EXTRA, {"schools": {}})
    for name, school in extra.get("schools", {}).items():
        schools.setdefault(name, {"team": name, "extra": True, **school})
    old = presto_cache()
    presto = {s["team"]: s for s in schools.values() if s["type"] == "Presto"}

    today = date.fromisoformat(TODAY) if TODAY else datetime.now(EASTERN).date()
    window = [today - timedelta(days=i) for i in range(FINALS_DAYS_BACK + 1)]
    games = [g for d in window for g in (read_json(SLATES / f"{d.isoformat()}.json") or {}).get("games", [])
             if not g.get("box_read") and not g.get("off")]
    playing = [t for t in dict.fromkeys(t for g in games for t in (g["home"], g["away"])) if t in presto]
    order = playing + [t for t in presto if t not in playing]

    pages = dict(old.get("pages", {}))
    boxes = dict(old.get("boxes", {}))
    budget = [PRESTO_BUDGET]

    def paced(fn, *args):
        if budget[0] <= 0:
            return
        if budget[0] < PRESTO_BUDGET:
            time.sleep(PRESTO_PACE)
        budget[0] -= 1
        fn(*args)

    def load(team):
        try:
            rows = schedule_rows(presto[team], fallback=False)
        except FETCH_ERRORS as exc:
            out["errors"].append(f"{team} schedule: {exc}")
            return
        if rows:
            pages[team] = [row_to_json(r) for r in rows]

    followups = []

    def read(url):
        try:
            page = get(url)
            box = None if page.lstrip().startswith("<?xml") else presto_box(page)
        except FETCH_ERRORS as exc:
            out["errors"].append(f"{url}: {exc}")
            return
        if box:
            boxes[url] = {"at": out["fetched_at"], "box": box}
        else:
            live = pt3_source(page, url)
            if live:
                followups.append((url, live))

    def read_live(url, live):
        try:
            box = pt3_box(get(live, as_json=True))
        except (*FETCH_ERRORS, TypeError, AttributeError) as exc:
            out["errors"].append(f"{live}: {exc}")
            return
        if box["sides"]:
            boxes[url] = {"at": out["fetched_at"], "box": box}

    for team in playing:
        paced(load, team)
    urls = set()
    for g in games:
        rows = {t: [row_from_json(r) for r in pages.get(t, [])] for t in (g["home"], g["away"])}
        link, _ = box_link(g, rows)
        urls.update(u for u in (link, g.get("boxscore"), g.get("link")) if presto_box_date(u))
    for url in sorted(urls, key=lambda u: (presto_box_date(u) != today, u)):
        paced(read, url)
    for url, live in followups:
        paced(read_live, url, live)
    for team in order[len(playing):]:
        paced(load, team)

    PRESTO_CACHE.write_text(json.dumps({"fetched_at": out["fetched_at"], "pages": pages, "boxes": boxes}, separators=(",", ":")))
    out["pages"], out["boxes"], out["requests"] = len(pages), len(boxes), PRESTO_BUDGET - budget[0]
    return out


def find_row(rows, day, opponent, exhibition=False):
    """The page's row for the game on `day` against `opponent`. A team rarely plays twice a day,
    so the date decides; opponent-name overlap breaks a tie. Exhibition rows count only for extra games.
    With exhibition=None either kind counts: a Division I host and its D3 guest often label the same game differently."""
    same_day = [r for r in rows if r["day"] == day and (exhibition is None or r["exhibition"] == exhibition)]
    if len(same_day) <= 1:
        return same_day[0] if same_day else None
    want = name_tokens(opponent)
    return max(same_day, key=lambda r: len(want & name_tokens(r["opponent"])))


# ---------------------------------------------------------------- opponents outside Division III

NAME_FILLER = {"university", "college", "the", "of", "at", "and"}


def site_of(url):
    """'http://www.odusports.com/' -> 'odusports.com'."""
    host = re.sub(r"^https?://", "", (url or "").strip().lower()).split("/")[0]
    return re.sub(r"^www\.", "", host)


def opponent_name(raw):
    """'#12 Old Dominion University (Exhibition)' -> 'Old Dominion'."""
    name = re.sub(r"\([^)]*\)|#\d+|\bNo\. \d+\b", " ", raw or "")
    name = re.sub(r"^\s*(?:vs\.?|at)\s+", "", name, flags=re.I)
    name = re.sub(r"^\s*The\s+", "", name.strip())
    name = re.sub(r"\s+(?:University|College)$", "", name.strip())
    return " ".join(name.split())


def name_key(name):
    return frozenset(w for w in re.findall(r"[a-z]+", opponent_name(name).lower()) if w not in NAME_FILLER)


def load_members():
    """{'site': {domain: row}, 'name': {name key: [rows]}} from data/ncaa_members.csv."""
    by_site, by_name = {}, {}
    if not MEMBERS.exists():
        return {"site": by_site, "name": by_name}
    with open(MEMBERS, newline="") as f:
        for m in csv.DictReader(f):
            m["division"] = int(m["division"])
            if m["site"]:
                by_site[m["site"]] = m
            by_name.setdefault(name_key(m["name"]), []).append(m)
    return {"site": by_site, "name": by_name}


def opponent_division(r, members):
    """The NCAA division of a schedule row's opponent: by the opponent link's site, then by a name that
    fits exactly one member. None for NAIA, two-year, and unknown opponents."""
    m = members["site"].get(site_of(r.get("opponent_url")))
    if not m:
        hits = members["name"].get(name_key(r["opponent"]), [])
        m = hits[0] if len(hits) == 1 else None
    return (m["division"], m) if m else (None, None)

PLACEHOLDER = re.compile(r"\b(?:Tournament|Tourney|Classic|Invitational|Tip-?Off|Challenge|Shootout|Showcase|TBA|TBD|"
                         r"Winner|Loser|Consolation|Semifinals?|Championship)\b|\S\s+(?:vs\.?|v\.)\s+\S", re.I)


def page_games(day, schools, pages, known, ranks, members):
    """Games on `day` between two D3 teams that a schedule page lists and `known` (the Stat Lab's list) lacks.
    A tournament's second-day game shows as TBA on the pages until the first day ends, so games.txt and
    gameLeverages.json pick it up a day late. The opponent resolves by its link's site, then by a name that fits
    one D3 school and no Division I or II member (Pacific). A game either page calls an exhibition or scrimmage
    stays out. Win chance and leverage stay at 0.5 and 0 until the
    next NPI update lists the game; the slate's previous entry keeps nothing, because the ids match."""
    resolve = opponent_resolver(schools, members)
    pairs = {frozenset((g["home"], g["away"])) for g in known}
    games = []
    for team, rows in sorted(pages.items()):
        if schools.get(team, {}).get("extra"):
            continue
        for r in rows:
            if r["day"] != day or r["exhibition"]:
                continue
            opp = resolve(r)
            if not opp or opp == team or frozenset((team, opp)) in pairs:
                continue
            # The other page can call it a scrimmage when this one does not (Lehman listed Merchant Marine plain,
            # Merchant Marine listed "Lehman (Scrimmage)", 2026-11-07).
            if any(o["exhibition"] for o in pages.get(opp, []) if o["day"] == day and resolve(o) == team):
                continue
            pairs.add(frozenset((team, opp)))
            home, away = (team, opp) if r["home"] else (opp, team)
            games.append({"date": day.isoformat(), "home": home, "away": away, "neutral": r["neutral"], "label": None,
                          "home_rank": ranks.get(home), "away_rank": ranks.get(away), "pregame_wp": 0.5, "pregame_margin": 0.0,
                          "modeled": False})
    return games


def opponent_resolver(schools, members):
    """A function from a schedule row to the D3 school its opponent names, or None: by the link's site, then by a
    name that fits one D3 school and no Division I or II member. A placeholder row ("WashU Tournament" linking the
    host's site) and a host's listing of another game ("Benedictine (Ill.) vs. Central College") name no opponent."""
    sites, keys, upper = team_sites(schools), d3_keys(schools), upper_sites(members)

    def resolve(r):
        if PLACEHOLDER.search(r["opponent"] or ""):
            return None
        site = site_of(r.get("opponent_url"))
        opp = sites.get(site)
        # A neutral row's link often points at the tournament host, not the opponent (Aurora's "Westminster
        # University" linked principiaathletics.com, 2026-11-07), so the link counts only when the name fits.
        if opp and r["neutral"] and not (name_key(r["opponent"]) & name_key(opp)):
            opp = None
        if not opp and site not in upper:
            hits = {keys[k] for k in name_keys(opponent_name(r["opponent"])) if k in keys}
            above = [m for m in members["name"].get(name_key(r["opponent"]), []) if m["division"] in (1, 2)]
            opp = hits.pop() if len(hits) == 1 and not above else None
        return opp
    return resolve


RESCHEDULE_DAYS = 3


def rescheduled(g, day, pages, resolve):
    """The day the schedule pages put a Stat Lab game on, when neither page lists the partner on `day` and the
    pages agree on one day within RESCHEDULE_DAYS. The Stat Lab listed La Verne vs Pacific on 2026-11-07 and
    2026-11-08; La Verne's page said Sunday the 8th only. None when the pages list it on `day` or say nothing."""
    found = set()
    for team, partner in ((g["home"], g["away"]), (g["away"], g["home"])):
        rows = [r for r in pages.get(team, []) if not r["exhibition"] and resolve(r) == partner]
        if any(r["day"] == day for r in rows):
            return None
        found |= {r["day"] for r in rows if 0 < abs((r["day"] - day).days) <= RESCHEDULE_DAYS}
    return found.pop() if len(found) == 1 else None


def place_games(games, days, pages, resolve, notes):
    """The Stat Lab's games for `days`, by day, after the schedule pages have their say: a projected pairing both
    pages contradict is left out, and a game the pages date differently moves to their day (or goes, when the
    list already has the pair there)."""
    by_day = {d: [] for d in days}
    listed = {(g["date"], frozenset((g["home"], g["away"]))) for g in games}
    for g in games:
        d = date.fromisoformat(g["date"])
        if d not in by_day:
            continue
        if contradicted(g, d, pages, resolve):
            notes.append(f'{g["away"]} at {g["home"]} {d.isoformat()}: both schedule pages list other opponents, left out')
            continue
        moved = rescheduled(g, d, pages, resolve)
        if moved and (moved.isoformat(), frozenset((g["home"], g["away"]))) in listed:
            notes.append(f'{g["away"]} at {g["home"]} {d.isoformat()}: the pages list it on {moved.isoformat()}, where the list has it too, left out')
            continue
        if moved:
            notes.append(f'{g["away"]} at {g["home"]} {d.isoformat()}: the pages list it on {moved.isoformat()}, moved')
            g = {**g, "date": moved.isoformat()}
            if moved not in by_day:
                continue
        by_day[date.fromisoformat(g["date"])].append(g)
    return by_day


HOST_ROW = re.compile(r"^(.*\S)\s+(?:vs\.?|v\.)\s+(\S.*)$", re.I)


def host_listings(day, pages, schools):
    """{frozenset((A, B)): row} for the rows a host's page lists as "A vs. B" on `day`, with both names resolving
    to one D3 school each. The host's live stats link is the feed for that game (Susquehanna listed "SUNY
    Cobleskill vs. Christopher Newport" with its own feed, 2026-11-07, while CNU's page linked CNU's idle feed)."""
    keys, out = d3_keys(schools), {}
    for rows in pages.values():
        for r in rows:
            m = HOST_ROW.match(r["opponent"] or "") if r["day"] == day else None
            if not m:
                continue
            teams = set()
            for part in m.groups():
                hits = {keys[k] for k in name_keys(opponent_name(part)) if k in keys}
                if len(hits) == 1:
                    teams |= hits
            if len(teams) == 2:
                out.setdefault(frozenset(teams), r)
    return out


def contradicted(g, day, pages, resolve):
    """True when each team's schedule page lists other D3 opponents on `day`, none of them the partner, and one of
    those opponents' pages names the team back. The Stat Lab's list carries a tournament's projected second-day
    pairings: Salisbury at Marywood, 2026-11-07, when the pages said Salisbury vs Widener and Marywood vs Centenary."""
    def named(team):
        return {resolve(r) for r in pages.get(team, []) if r["day"] == day and not r["exhibition"]} - {None}
    for team, partner in ((g["home"], g["away"]), (g["away"], g["home"])):
        others = named(team)
        if not others or partner in others or not any(team in named(o) for o in others):
            return False
    return True


def other_games(day, schools, pages, members, ranks, covered):
    """Games on `day` between a D3 team and a Division I or II team, read from the D3 team's page."""
    games, hosts = [], {}
    for team, rows in pages.items():
        school = schools.get(team)
        if not school or school.get("extra") or (day.isoformat(), team) in covered:
            continue
        for r in rows:
            if r["day"] != day:
                continue
            division, member = opponent_division(r, members)
            if division not in (1, 2):
                continue
            opp = opponent_name(r["opponent"])
            if r["home"]:
                home, away = team, opp
            else:
                home, away = opp, team
            games.append({"date": day.isoformat(), "home": home, "away": away, "neutral": r["neutral"],
                          "label": "Exhibition" if r["exhibition"] else None, "division": division, "d3": team,
                          "home_rank": ranks.get(home), "away_rank": ranks.get(away), "pregame_wp": 0.5, "pregame_margin": 0.0,
                          "modeled": False})
            if member["site"] and opp not in schools:
                # The host's own schedule page fills a tipoff or live stats link the D3 page leaves out, and its
                # Sidearm feed is a fallback. Its times print without a zone; the D3 team's zone is the best guess.
                hosts[opp] = {"team": opp, "type": "Sidearm", "schedule": f"https://{member['site']}/sports/womens-basketball/schedule",
                              "tz": school["tz"], "extra": True}
    return games, hosts


# ---------------------------------------------------------------- live feeds

_feed_cache = {}


def live_feed(url):
    """The machine-readable feed behind a live stats link, or None when there is none."""
    if not url:
        return None
    if url in _feed_cache:
        return _feed_cache[url]
    feed = None
    try:
        m = re.match(r"https?://(?:www\.)?sidearmstats\.com/([^/]+)/([^/?#]+)", url)
        p = re.match(r"https?://(?:www\.)?prestolivestats\.com/([^/]+)/([^/?#]+)", url)
        s = re.match(r"(https?://[^/]+)/sidearmstats/([^/?#]+)", url)
        if m:
            feed = {"type": "sidearm", "url": f"https://sidearmstats.com/{m.group(1)}/{m.group(2)}/game.json"}
        elif p:
            feed = {"type": "presto", "url": f"https://data.prestolivestats.com/xml/{p.group(1)}/events/{p.group(2)}.xml"}
        elif s:
            client = sidearm_client(s.group(1), url)
            if client:
                feed = {"type": "sidearm", "url": f"https://sidearmstats.com/{client}/{s.group(2)}/game.json"}
    except FETCH_ERRORS:
        feed = None
    _feed_cache[url] = feed
    return feed


_client_cache = {}


def sidearm_client(site, url):
    """The Sidearm client a school's stats pages publish under, read from the page at `url`. The crew publishes
    under the folder name, which can differ from the client name (Case Western: client "casewestern", folder
    "case"). A school has one client, so one page read serves its other feeds (wbball2) with no second read."""
    if site not in _client_cache:
        page = get(url)
        client = (re.search(r'livestats_foldername\s*=\s*"([^"]+)"', page)
                  or re.search(r'client_shortname\s*=\s*"([^"]+)"', page))
        if not client:
            return None
        _client_cache[site] = client.group(1)
    return _client_cache[site]


SIBLING_FEEDS = 2  # a host's other courts: wbball2 and wbball3


def sibling_feeds(feed):
    """A Sidearm host's other women's basketball feeds. A tournament host runs its own game on wbball and the
    other game on wbball2 (Hope's Michele Schoon Tournament, 2026-11-07), and the schools' pages can link either
    folder until the crews settle which game is on which."""
    if (feed or {}).get("type") != "sidearm":
        return []
    m = re.match(r"(https://sidearmstats\.com/[^/]+/)([a-z]+?)(\d*)/game\.json$", feed["url"])
    if not m:
        return []
    folders = [m.group(2)] + [f"{m.group(2)}{n}" for n in range(2, SIBLING_FEEDS + 2)]
    return [{"type": "sidearm", "url": f"{m.group(1)}{x}/game.json"} for x in folders if x != m.group(2) + m.group(3)]


def sibling_link(link, feed):
    """The stats page behind `feed` when `link` is the same host's page for another folder; else `link` as is."""
    folder = re.search(r"/([a-z]+?\d*)/game\.json$", feed["url"]).group(1)
    return re.sub(r"/sidearmstats/[a-z]+?\d*/", f"/sidearmstats/{folder}/", link) if link else link


def sidearm_sides(g):
    return {k: {"name": (g.get(key) or {}).get("Name"), "id": (g.get(key) or {}).get("Id")}
            for k, key in (("H", "HomeTeam"), ("V", "VisitingTeam"))}


def find_sibling(game, day):
    """The host's other feed, or an alternative feed the pages gave, that shows this game today, or None. Reads
    each candidate's game.json (about 4 KB)."""
    seen = []
    for feed in sibling_feeds(game.get("feed")) + [a["feed"] for a in game.get("alt_feeds") or []]:
        if feed in seen or feed.get("type") != "sidearm" or feed == game.get("feed"):
            continue
        seen.append(feed)
        try:
            g = get(feed["url"], as_json=True)["Game"]
        except (*FETCH_ERRORS, TypeError, AttributeError):
            continue
        if g.get("HasStarted") and feed_date_matches(g.get("Date"), day) and feed_is_game(game, sidearm_sides(g), {}):
            return feed
    return None


def adopt_feed(game, feed):
    alt = next((a for a in game.get("alt_feeds") or [] if a["feed"] == feed), None)
    game["link"] = alt["link"] if alt and alt.get("link") else sibling_link(game.get("link"), feed)
    game["feed"] = feed


def sidearm_over(g):
    """True when a Sidearm feed's game is over. Some crews never set IsComplete (Butler, 2026-10-28), so the clock
    at 0:00 in the last period of regulation or later, with no tie, also counts."""
    regulation = 2 if num((g.get("Rules") or {}).get("PeriodMinutes")) >= 20 else 4
    return bool(g.get("IsComplete")) or (num(g.get("Period")) >= regulation and g.get("ClockSeconds") == 0
                                         and num(g["HomeTeam"].get("Score")) != num(g["VisitingTeam"].get("Score")))


def house_feed(school):
    """A Sidearm school's own women's basketball feed, used when a home game has no live stats link yet. The feed
    answers 404 until the school's first game starts, so a 404 before tipoff says nothing about the game."""
    if not school or school["type"] != "Sidearm":
        return None
    host = re.match(r"(https?://[^/]+)", school["schedule"]).group(1)
    feed = live_feed(f"{host}/sidearmstats/wbball")
    return feed if feed and feed["type"] == "sidearm" else None


# ---------------------------------------------------------------- Sidearm hub and ESPN

HUB = "https://aggregation-service.sidearmsports.com/services/games.ashx"
ESPN = "https://site.api.espn.com/apis/site/v2/sports/basketball/womens-college-basketball"


def hub_games(day):
    """Women's basketball games on `day` from the feed behind sidearmstats.com/hub: every game a Sidearm school
    lists, with tipoff in UTC, both teams' sites, and the live stats link. It answers only for about yesterday
    through tomorrow. A TBA game carries midnight UTC on its date, so the window opens then and the date field
    picks the day. `listing_home` says which side posted the listing; its live stats link belongs to that side."""
    start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    query = urllib.parse.urlencode({"start_date": start.isoformat().replace("+00:00", "Z"),
                                    "end_date": (start + timedelta(hours=36)).isoformat().replace("+00:00", "Z")})
    out = []
    for g in get(f"{HUB}?{query}", as_json=True).get("data") or []:
        info, home, away = g.get("date_info") or {}, g.get("home_team"), g.get("away_team")
        if (g.get("sport") or {}).get("shortname") != "wbball" or (info.get("date") or "")[:10] != day.isoformat() \
                or not isinstance(home, dict) or not isinstance(away, dict) or g.get("status") == "C":
            continue
        timed = not info.get("tbd") and not info.get("all_day") and info.get("datetime_utc")
        names = f"{home.get('name') or ''} {away.get('name') or ''}"
        han = (g.get("location") or {}).get("han")
        out.append({"home": home.get("name") or "", "away": away.get("name") or "", "division": (g.get("division") or {}).get("name"),
                    "home_site": site_of(home.get("website")), "away_site": site_of(away.get("website")),
                    "home_id": home.get("school_global_id"), "away_id": away.get("school_global_id"),
                    "neutral": han == "N", "listing_home": han != "A",
                    "exhibition": bool(re.search(r"exhib|scrimmage", g.get("game_promotion_name") or "", re.I)
                                       or re.search(r"\(ex|exhib|scrimmage", names, re.I)),
                    "tip": info["datetime_utc"] if timed else None, "livestats": (g.get("media") or {}).get("livestats")})
    return out


def espn_games(day):
    """Regular-season Division I games on `day` from ESPN's scoreboard. A team outside Division I has no conference
    and isActive false. ESPN lists no exhibitions."""
    out = []
    for e in get(f"{ESPN}/scoreboard?dates={day:%Y%m%d}&groups=50&limit=500", as_json=True).get("events") or []:
        c = e["competitions"][0]
        tip = datetime.fromisoformat(e["date"].replace("Z", "+00:00"))
        if tip.astimezone(EASTERN).date() != day:
            continue
        sides = {x["homeAway"]: {"name": x["team"].get("location") or "", "d1": bool(x["team"].get("isActive"))} for x in c["competitors"]}
        if "home" in sides and "away" in sides:
            out.append({"id": e["id"], "home": sides["home"], "away": sides["away"], "neutral": bool(c.get("neutralSite")),
                        "tip": None if (c.get("timeValid") is False) else tip.isoformat().replace("+00:00", "Z")})
    return out


def espn_feed(event_id):
    """The game's light ESPN feed (about 14 KB) and its summary with player box scores (about 500 KB). Both allow
    reads from any site."""
    return {"type": "espn", "url": f"{ESPN}/scoreboard/{event_id}", "full": f"{ESPN}/summary?event={event_id}"}


def name_keys(name):
    """Spellings of a team name for matching ESPN's: 'Fitchburg St.' -> {'fitchburgst', 'fitchburgstate'}."""
    base = re.sub(r"[^a-z()]", "", name.lower().replace("&", "and"))
    return {base, re.sub(r"st$", "state", base) if re.search(r"\bSt\.?$", name) else base, re.sub(r"[()]", "", base)}


def team_sites(schools):
    """{site: team} for D3 schools whose schedule page sits on their own site (not a conference site several share)."""
    by_site = {}
    for team, s in schools.items():
        if not s.get("extra") and s.get("schedule"):
            by_site.setdefault(site_of(s["schedule"]), []).append(team)
    return {site: teams[0] for site, teams in by_site.items() if len(teams) == 1}


def d3_keys(schools):
    """{name key: team} for D3 schools, keeping only keys that fit one school."""
    keys = {}
    for team, s in schools.items():
        if not s.get("extra"):
            for k in name_keys(team):
                keys.setdefault(k, set()).add(team)
    return {k: next(iter(v)) for k, v in keys.items() if len(v) == 1}


def hub_teams(h, sites, keys, others=frozenset(), by_name=True):
    """(home, away) as D3 team names, None for a team outside Division III. The hub's team sites do not always
    match ours (SUNY Geneseo: knights.geneseo.edu, schedule on geneseoknights.com), so the listing team's live
    stats link and then the name are fallbacks. A site in `others` (Division I and II members) rules out a name match,
    because names repeat across divisions (Pacific). With by_name False, only sites count."""
    def which(name, *hosts):
        found = next((sites[s] for s in hosts if s in sites), None)
        if found or others & set(hosts) or not by_name:
            return found
        return next((keys[k] for k in name_keys(hub_name(name)) if k in keys), None)
    stats = site_of(h["livestats"])
    return (which(h["home"], h["home_site"], *([stats] if h.get("listing_home", True) else [])),
            which(h["away"], h["away_site"], *([] if h.get("listing_home", True) else [stats])))


def hub_name(raw):
    """A hub team name for matching: exhibition marks and "University" or "College" go, a state qualifier stays,
    so "Bethel University (Ind.)" stays apart from Bethel in Minnesota."""
    name = re.sub(r"\((?:exhibition|exh?\.?)\)", "", raw or "", flags=re.I)
    return " ".join(re.sub(r"\b(?:University|College)\b", "", name).split())


def upper_sites(members):
    return frozenset(s for s, m in members["site"].items() if m["division"] in (1, 2))


def find_hub(g, hub, schools, others=frozenset()):
    """The hub's listing of game g: one D3 team matches and the other team's names share a word, so a namesake
    listing (Thomas University for Thomas in Maine) does not count. NAIA listings are skipped."""
    sites, keys = team_sites(schools), d3_keys(schools)
    for h in hub:
        if h["division"] not in ("DI", "DII", "DIII"):
            continue
        home, away = hub_teams(h, sites, keys, others)
        for mine, theirs, other_mine, other_theirs in ((home, g["home"], g["away"], h["away"]), (away, g["away"], g["home"], h["home"])):
            if mine and mine == theirs and name_tokens(other_mine) & name_tokens(hub_name(other_theirs)):
                return h
    return None


def find_espn(g, espn, keys):
    """ESPN's listing of game g: the D3 team's name matches ESPN's non-D1 team, and the other names share a word."""
    for e in espn:
        for mine, theirs, other_mine, other_theirs in ((g["home"], e["home"], g["away"], e["away"]), (g["away"], e["away"], g["home"], e["home"])):
            if not theirs["d1"] and any(keys.get(k) == mine for k in name_keys(theirs["name"])) \
                    and name_tokens(other_mine) & name_tokens(other_theirs["name"]):
                return e
    return None


def espn_confirmed(g, day, schools, pages):
    host = g["away"] if g["home"] == g["d3"] else g["home"]
    site = site_of(schools[g["d3"]].get("schedule"))
    return any(r["day"] == day and site_of(r.get("opponent_url")) == site for r in pages.get(host, []))


def listed_games(day, hub, espn, schools, members, ranks, taken, blocked):
    """Games against Division I and II teams that no D3 schedule page gave. From the hub, with the D3 team found by
    its site only: D3 pages often leave out an exhibition at a Division I school (Spalding at Bellarmine). From
    ESPN only for a team in `blocked`, whose page could not be read, marked "espn" for collect() to check against
    the host's page. `taken` holds the D3 teams that already have a game that day. Returns the games and host
    entries for opponents outside schools.csv, as other_games() does."""
    sites, keys, games, hosts = team_sites(schools), d3_keys(schools), [], {}
    # A team plays once a day. A school's listing can carry the wrong opponent record (Indiana's "Marian" with
    # Marian of Wisconsin's site, while Marian of Indiana lists the game too), so a team the hub puts against two
    # different schools that day adds nothing. NAIA listings count here.
    faced = {}
    for h in hub:
        if h.get("home_id") and h.get("away_id"):
            faced.setdefault(h["home_id"], set()).add(h["away_id"])
            faced.setdefault(h["away_id"], set()).add(h["home_id"])

    def add(team, opp, team_home, neutral, label, division, tip, site, **mark):
        home, away = (team, opp) if team_home else (opp, team)
        games.append({"date": day.isoformat(), "home": home, "away": away, "neutral": neutral, "label": label,
                      "division": division, "d3": team, "home_rank": ranks.get(home), "away_rank": ranks.get(away),
                      "pregame_wp": 0.5, "pregame_margin": 0.0, "tip": tip, **mark})
        taken.add(team)
        if site and opp not in schools:
            hosts[opp] = {"team": opp, "type": "Sidearm", "schedule": f"https://{site}/sports/womens-basketball/schedule",
                          "tz": schools[team]["tz"], "extra": True}

    for h in hub:
        # The listing school's division; an NAIA school's listing of a game is about NAIA teams.
        if h["division"] not in ("DI", "DII", "DIII"):
            continue
        home_team, away_team = hub_teams(h, sites, keys, by_name=False)
        team = home_team or away_team
        if bool(home_team) == bool(away_team) or team in taken \
                or any(len(faced.get(h.get(k), ())) > 1 for k in ("home_id", "away_id")):
            continue
        raw = h["away"] if home_team else h["home"]
        member = members["site"].get(h["away_site"] if home_team else h["home_site"])
        if not member and hub_name(raw) == hub_name(re.sub(r"\([^)]*\)", "", raw)):
            # By name only when no state qualifier says it is another school ("Holy Cross College (Ind.)").
            hits = members["name"].get(name_key(raw), [])
            member = hits[0] if len(hits) == 1 else None
        if member and member["division"] in (1, 2):
            add(team, opponent_name(raw), bool(home_team), h["neutral"], "Exhibition" if h.get("exhibition") else None,
                member["division"], h["tip"], member["site"])
    for e in espn:
        for mine, other, team_home in ((e["home"], e["away"], True), (e["away"], e["home"], False)):
            team = next((keys[k] for k in name_keys(mine["name"]) if k in keys), None)
            if team and team in blocked and team not in taken and not mine["d1"] and other["d1"]:
                hits = members["name"].get(name_key(other["name"]), [])
                if len(hits) == 1:
                    add(team, other["name"], team_home, e["neutral"], None, 1, e["tip"], hits[0]["site"], source="espn")
    return games, hosts


# ---------------------------------------------------------------- finals and newcomers

def game_score(s):
    """Hollinger game score from a box line."""
    return (s["pts"] + 0.4 * s["fgm"] - 0.7 * s["fga"] - 0.4 * (s["fta"] - s["ftm"]) + 0.7 * s["oreb"] + 0.3 * s["dreb"]
            + s["stl"] + 0.7 * s["ast"] + 0.7 * s["blk"] - 0.4 * s["pf"] - s["to"])


TOP_N = 15  # the page shows the 15 best game scores of the night; one team can supply all 15


def line_name(line):
    """'First Last' from a box line. Feeds give first and last, 'LAST,FIRST', or 'Last, First'; all-caps words soften."""
    if line.get("first") and line.get("last"):
        name = f'{line["first"]} {line["last"]}'
    else:
        name = re.sub(r"^\s*(.+?),\s*(.+)$", r"\2 \1", line.get("abbr") or "")
    return " ".join(w[0] + w[1:].lower() if len(w) > 1 and w.isupper() else w for w in name.split())


def played(s):
    """True when the box line shows the player on the floor. Some crews leave minutes blank."""
    return (s.get("min") or 0) > 0 or any((s.get(k) or 0) > 0 for k in ("pts", "reb", "ast", "stl", "blk", "fga", "fta", "to", "pf"))


def made_attempted(v):
    m = re.match(r"\s*(\d+)\s*-\s*(\d+)", str(v or ""))
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def num(v):
    try:
        return int(float(str(v).strip() or 0))
    except ValueError:
        return 0


def sidearm_lines(full):
    """{'H'|'V': [{'first','last','abbr', stats...}]} from a ?detail=full Sidearm feed."""
    out = {}
    for side, key in (("H", "HomeTeam"), ("V", "VisitingTeam")):
        # A feed read before its game starts can carry no stats block yet.
        team = (full.get("Stats") or {}).get(key) or {}
        people = {p.get("PersonId"): p for p in team.get("Players") or [] if p.get("PersonId")}
        by_uni = {p.get("UniformNumber"): p for p in team.get("Players") or []}
        lines = []
        for v in ((team.get("PlayerGroups") or {}).get("Players") or {}).get("Values") or []:
            person = people.get(v.get("PersonId")) or by_uni.get(v.get("Uni")) or {}
            fgm, fga = made_attempted(v.get("Fgam"))
            ftm, fta = made_attempted(v.get("Ftma"))
            lines.append({"first": person.get("FirstName", ""), "last": person.get("LastName", ""), "abbr": v.get("Name", ""),
                          "min": num(v.get("Minutes")), "pts": num(v.get("Points")), "fgm": fgm, "fga": fga, "ftm": ftm, "fta": fta,
                          "oreb": num(v.get("OffensiveRebounds")), "dreb": num(v.get("DefensiveRebounds")), "reb": num(v.get("TotalRebounds")),
                          "ast": num(v.get("Assists")), "to": num(v.get("Turnovers")), "stl": num(v.get("Steals")),
                          "blk": num(v.get("Blocks")), "pf": num(v.get("PersonalFouls"))})
        out[side] = lines
    return out


def presto_lines(root):
    """{'H'|'V': [...]} from StatCrew XML: <team vh><player name checkname><stats .../></player></team>."""
    out = {}
    for team in root.iter("team"):
        lines = []
        for p in team.iter("player"):
            s = p.find("stats")
            if s is None or p.get("code") == "TM":
                continue
            a = s.attrib
            name = p.get("name") or p.get("checkname") or ""
            last, _, first = name.partition(",") if "," in name else (name.split(" ")[-1], "", " ".join(name.split(" ")[:-1]))
            lines.append({"first": first.strip(), "last": last.strip(), "abbr": name, "min": num(a.get("min")),
                          "pts": num(a.get("tp")), "fgm": num(a.get("fgm")), "fga": num(a.get("fga")), "ftm": num(a.get("ftm")),
                          "fta": num(a.get("fta")), "oreb": num(a.get("oreb")), "dreb": num(a.get("dreb")), "reb": num(a.get("treb")),
                          "ast": num(a.get("ast")), "to": num(a.get("to")), "stl": num(a.get("stl")), "blk": num(a.get("blk")),
                          "pf": num(a.get("pf"))})
        out[team.get("vh")] = lines
    return out


BOX_COLUMNS = {"MIN": "min", "PTS": "pts", "REB": "reb", "A": "ast", "AST": "ast", "TO": "to", "STL": "stl", "BLK": "blk", "PF": "pf"}


def sidearm_box(page):
    """A Sidearm box score page: {'date': 'M/D/YYYY', 'sides': {...}, 'score': {...}, 'lines': {...}}, keyed 'V' and
    'H' like a feed, or None when the page lacks two player tables. The page lists the visiting team first."""
    soup = BeautifulSoup(page, "html.parser")
    tables = [t for t in soup.select("table.overall-stats") if t.select_one("thead") and "Player" in t.select_one("thead").get_text()]
    board = soup.select_one("table.sidearm-table")
    teams = [tr for tr in (board.select("tr")[1:] if board else []) if tr.find_all("td")]
    # Some pages add a box score per period after the full game's two tables.
    if len(tables) < 2 or len(teams) != 2:
        return None
    tables = tables[:2]
    board_heads = [c.get_text(" ", strip=True) for c in board.select("tr")[0].find_all(["th", "td"])]
    total = next((i for i, h in enumerate(board_heads) if h.startswith("Total")), None)
    if total is None:
        return None
    sides, score, lines = {}, {}, {}
    for side, tr, table in zip(("V", "H"), teams, tables):
        cells = tr.find_all(["th", "td"])
        label = re.sub(r"^\s*Winner\s+", "", cells[0].get_text(" ", strip=True))
        code, _, name = label.partition(" ")
        sides[side] = {"name": name or code, "id": code}
        score[side] = num(cells[total].get_text(strip=True)) if total < len(cells) else 0
        heads = [c.get_text(" ", strip=True) for c in table.select("thead tr")[-1].find_all(["th", "td"])]
        out = []
        for row in table.select("tbody tr"):
            v = dict(zip(heads, row.find_all(["th", "td"])))
            who = v.get("Player")
            if who is None:
                continue
            for jersey in who.select(".mobile-jersey-number"):
                jersey.decompose()
            abbr = re.sub(r"\s*,\s*", ", ", who.get_text(" ", strip=True))
            if not abbr or abbr.upper() == "TEAM":
                continue
            last, _, first = abbr.partition(", ")
            stat = {key: num(v[col].get_text(strip=True)) for col, key in BOX_COLUMNS.items() if col in v}
            fgm, fga = made_attempted(v["FG"].get_text(strip=True) if "FG" in v else "")
            ftm, fta = made_attempted(v["FT"].get_text(strip=True) if "FT" in v else "")
            oreb, dreb = made_attempted(v["ORB-DRB"].get_text(strip=True) if "ORB-DRB" in v else "")
            out.append({"first": first.strip(), "last": last.strip(), "abbr": abbr, "fgm": fgm, "fga": fga, "ftm": ftm,
                        "fta": fta, "oreb": oreb, "dreb": dreb, **{k: 0 for k in BOX_COLUMNS.values()}, **stat})
        lines[side] = out
    when = re.search(r"\bon (\d{1,2}/\d{1,2}/\d{4})", soup.title.get_text() if soup.title else "")
    return {"date": when.group(1) if when else None, "sides": sides, "score": score, "lines": lines}


PRESTO_COLUMNS = {"MIN": "min", "PTS": "pts", "OREB": "oreb", "DREB": "dreb", "REB": "reb", "AST": "ast", "STL": "stl",
                  "BLK": "blk", "TO": "to", "PF": "pf"}
PRESTO_SKIP = {"team", "totals", "starters", "reserves", "bench"}


def presto_box(page):
    """A Presto box score page (the `boxscores/<date>_<id>.xml` link serves HTML): {'status', 'complete', 'sides',
    'score', 'lines'} keyed 'V' and 'H' like a feed, or None when the page lacks the linescore or two player tables.
    The page updates during the game, so it also gives a live score. Its date line can run a day ahead (UTC), so
    the date comes from the link."""
    soup = BeautifulSoup(page, "html.parser")
    board = soup.select_one(".linescore table") or soup.select_one("table.table")
    teams = [tr for tr in board.select("tr") if tr.find("td")] if board else []
    tables = [t for t in soup.select("table") if t.select("thead tr")
              and {"Player", "MIN"} <= {c.get_text(" ", strip=True) for c in t.select("thead tr")[-1].find_all(["th", "td"])}]
    if len(teams) != 2 or len(tables) < 2:
        return None
    status = board.select_one("tr th").get_text(" ", strip=True)
    sides, score, lines = {}, {}, {}
    for side, tr, table in zip(("V", "H"), teams, tables[:2]):
        sides[side] = {"name": tr.find("th").get_text(" ", strip=True)}
        total = tr.select_one("td.total") or tr.find_all("td")[-1]
        score[side] = num(total.get_text(strip=True))
        heads = [c.get_text(" ", strip=True) for c in table.select("thead tr")[-1].find_all(["th", "td"])]
        out = []
        for row in table.select("tbody tr"):
            cells = row.find_all(["th", "td"])
            if len(cells) < len(heads):
                continue
            v = dict(zip(heads, (c.get_text(" ", strip=True) for c in cells)))
            # Most templates mark the name (.player-name); others write "F 5 Marissa Nudd" or "25 - Long,Caroline - F".
            marked = cells[heads.index("Player")].select_one(".player-name") if "Player" in heads else None
            name = marked.get_text(" ", strip=True) if marked else v.get("Player", "").strip()
            name = re.sub(r"^(?:[A-Z]{1,2}(?:/[A-Z]{1,2})?\s+)?(?:\d+\s*-?|-)\s+", "", name)
            name = re.sub(r"\s+-\s+[A-Z]{1,2}(?:/[A-Z]{1,2})?$", "", name).strip()
            if not name or name.lower() in PRESTO_SKIP:
                continue
            if "," in name:
                last, _, first = (s.strip() for s in name.partition(","))
            else:
                first, _, last = name.partition(" ")
            fgm, fga = made_attempted(v.get("FGM-A"))
            ftm, fta = made_attempted(v.get("FTM-A"))
            out.append({"first": first, "last": last, "abbr": name, "fgm": fgm, "fga": fga, "ftm": ftm, "fta": fta,
                        **{key: num(v.get(col)) for col, key in PRESTO_COLUMNS.items()}})
        lines[side] = out
    return {"status": status, "complete": status.lower().startswith("final"), "sides": sides, "score": score, "lines": lines}


def presto_box_date(url):
    """'.../boxscores/20261106_h03q.xml' -> date(2026, 11, 6), or None."""
    m = re.search(r"/boxscores/(\d{4})(\d{2})(\d{2})_", url or "")
    return date(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def espn_lines(summary):
    """{'H'|'V': [...]} from an ESPN summary. Each team's statistics list names its columns (MIN, PTS, FG as
    "made-attempted", and so on); the header says which team is home."""
    side = {c["team"]["id"]: "H" if c["homeAway"] == "home" else "V" for c in summary["header"]["competitions"][0]["competitors"]}
    out = {}
    for team in (summary.get("boxscore") or {}).get("players") or []:
        block = (team.get("statistics") or [{}])[0]
        names = block.get("names") or block.get("labels") or []
        lines = []
        for a in block.get("athletes") or []:
            v = dict(zip(names, a.get("stats") or []))
            if not v:
                continue  # did not play
            full = a["athlete"].get("displayName") or ""
            first, _, last = full.partition(" ")
            fgm, fga = made_attempted(v.get("FG"))
            ftm, fta = made_attempted(v.get("FT"))
            lines.append({"first": first, "last": last, "abbr": a["athlete"].get("shortName") or full, "min": num(v.get("MIN")),
                          "pts": num(v.get("PTS")), "fgm": fgm, "fga": fga, "ftm": ftm, "fta": fta, "oreb": num(v.get("OREB")),
                          "dreb": num(v.get("DREB")), "reb": num(v.get("REB")), "ast": num(v.get("AST")), "to": num(v.get("TO")),
                          "stl": num(v.get("STL")), "blk": num(v.get("BLK")), "pf": num(v.get("PF"))})
        out[side.get(team["team"]["id"], "V")] = lines
    return out


def norm(name):
    return re.sub(r"[^a-z]", "", (name or "").lower())


def match_newcomer(line, roster):
    """The roster newcomer this box line belongs to. Full first and last name when the feed has them;
    otherwise first initial plus last name, and only when exactly one newcomer fits."""
    if line["first"] and line["last"]:
        full = norm(line["first"] + line["last"])
        hit = [p for p in roster if norm(p["name"]) == full]
        if hit:
            return hit[0]
    m = re.match(r"\s*([A-Za-z])[a-z]*\.?\s+(.+)$", line["abbr"]) or re.match(r"\s*(.+?),\s*([A-Za-z])", line["abbr"])
    if not m:
        return None
    initial, last = (m.group(1), m.group(2)) if "," not in line["abbr"] else (m.group(2), m.group(1))
    last_n = norm(last)
    hit = [p for p in roster if norm(p["name"].split(" ")[-1]) == last_n and norm(p["name"])[:1] == initial.lower()]
    return hit[0] if len(hit) == 1 else None


def feed_date_matches(feed_date, day):
    return feed_date == f"{day.month}/{day.day}/{day.year}"


def read_final(game):
    """Read a game's feed once. Returns {'home','away','newcomers':[...]} when the feed reports it complete."""
    feed = game.get("feed")
    if not feed:
        return None
    day = date.fromisoformat(game["date"])
    if feed["type"] == "espn":
        summary = get(feed["full"], as_json=True)
        comp = summary["header"]["competitions"][0]
        if not comp["status"]["type"].get("completed"):
            return None
        sides = {c["homeAway"]: c for c in comp["competitors"]}
        home_score, away_score = num(sides["home"].get("score")), num(sides["away"].get("score"))
        feed_sides = {k: {"name": sides[h]["team"].get("location"), "id": sides[h]["team"].get("abbreviation")}
                      for k, h in (("H", "home"), ("V", "away"))}
        lines = espn_lines(summary)
    elif feed["type"] == "sidearm":
        full = get(feed["url"] + "?detail=full", as_json=True)
        g = full["Game"]
        if not feed_date_matches(g.get("Date"), day) or not feed_is_game(game, sidearm_sides(g), sidearm_lines(full)):
            # The feed shows another game. A tournament host runs the other game on another court's feed.
            sibling = find_sibling(game, day)
            if not sibling:
                return None
            adopt_feed(game, sibling)
            full = get(sibling["url"] + "?detail=full", as_json=True)
            g = full["Game"]
        if not sidearm_over(g):
            return None
        home_score, away_score = num(g["HomeTeam"]["Score"]), num(g["VisitingTeam"]["Score"])
        feed_sides, lines = sidearm_sides(g), sidearm_lines(full)
    else:
        root = ET.fromstring(get(feed["url"]))
        venue, status = root.find(".//venue"), root.find(".//status")
        if venue is None or status is None or status.get("complete") != "Y" or not feed_date_matches(venue.get("date"), day):
            return None
        scores = {t.get("vh"): num((t.find("linescore").attrib if t.find("linescore") is not None else {}).get("score")) for t in root.iter("team")}
        home_score, away_score = scores.get("H", 0), scores.get("V", 0)
        feed_sides = {"H": {"name": venue.get("homename")}, "V": {"name": venue.get("visname")}}
        for t in root.iter("team"):
            if t.get("vh") in feed_sides:
                feed_sides[t.get("vh")] = {"name": t.get("name") or feed_sides[t.get("vh")]["name"], "id": t.get("id")}
        lines = presto_lines(root)
        if not feed_is_game(game, feed_sides, lines):
            return None
    return box_result(game, home_score, away_score, feed_sides, lines)


# ---------------------------------------------------------------- slates

def tip_time(r, day):
    if not r or not r["time"]:
        return None, True
    hour, minute, zone = r["time"]
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=ZoneInfo(zone)).astimezone(timezone.utc).isoformat().replace("+00:00", "Z"), False


def box_result(game, home_score, away_score, sides, lines):
    """The stored final: score, newcomer lines, and each team's 15 best lines, oriented to the schedule's home and away."""
    # The feed's home side follows the stat crew, and so do its labels; flip when the evidence says so.
    if should_flip(game, sides, lines):
        home_score, away_score = away_score, home_score
        lines = {"H": lines.get("V", []), "V": lines.get("H", [])}
    found = []
    for side, team, roster in (("H", game["home"], game["newcomers_home"]), ("V", game["away"], game["newcomers_away"])):
        for line in lines.get(side, []):
            who = match_newcomer(line, roster)
            if who and played(line):
                found.append({"team": team, "name": who["name"], "reason": who["reason"], "gmsc": round(game_score(line), 1),
                              "line": {k: line[k] for k in ("min", "pts", "reb", "ast", "stl", "blk", "fgm", "fga")}})
    # The page can filter the list by team rank, so each team keeps its own 15 best: one team can fill the list alone.
    top = []
    for side, team in (("H", game["home"]), ("V", game["away"])):
        mine = [{"team": team, "name": line_name(line), "reason": "", "gmsc": round(game_score(line), 1),
                 "line": {k: line[k] for k in ("min", "pts", "reb", "ast", "stl", "blk", "fgm", "fga")}}
                for line in lines.get(side, []) if played(line)]
        top += sorted(mine, key=lambda x: -x["gmsc"])[:TOP_N]
    return {"home": home_score, "away": away_score, "newcomers": sorted(found, key=lambda x: -x["gmsc"]),
            "top": sorted(top, key=lambda x: -x["gmsc"])}


PT3_HASH = re.compile(r"eventIdHashCode\s*=\s*'([^']+)'")
PT3_ENTRY = re.compile(r"gamedayServiceEntryPointUrl\s*=\s*'([^']+)'")
PT3_STATS = {"fgm": "fgm", "fga": "fga", "ftm": "ftm", "fta": "fta", "min": "min", "tp": "pts", "oreb": "oreb", "dreb": "dreb",
             "treb": "reb", "ast": "ast", "stl": "stl", "blk": "blk", "to": "to", "pf": "pf"}


def pt3_source(page, url):
    """The live update URL a new-template Presto box score page loads its numbers from, or None. The page itself
    holds empty tables and a `conf` block with the event hash (SUNY Delhi, Curry, Eureka, 2026-11-08); the JSON
    lives on the school's own site at /action/sports/liveupdate?e=<event>&h=<hash>."""
    h, e = PT3_HASH.search(page or ""), PT3_ENTRY.search(page or "")
    return absolute(e.group(1) + "h=" + urllib.parse.quote(h.group(1)), url) if h and e else None


def pt3_box(data):
    """{'status', 'complete', 'sides', 'score', 'lines'} like presto_box(), from PrimeTime3 live JSON (the
    "Basketball LiveStats In-Arena Tool" export: status, venue rules, and team[].linescore, totals, player)."""
    if isinstance(data.get("data"), str):
        data = json.loads(data["data"])

    def one(v):
        return num(v[0] if isinstance(v, list) else v)
    status = data.get("status") or {}
    complete = status.get("complete") == "Y"
    periods = status.get("period") or []
    period = one(periods[-1]) if periods else 0
    regulation = one((data.get("venue") or {}).get("rules", {}).get("prds")) or 4
    if complete:
        text = "Final" + (" (OT)" if period > regulation else "")
    elif period:
        text = f"{status.get('clock') or ''} " + (f"Q{period}" if period <= regulation else f"OT{period - regulation}" if period > regulation + 1 else "OT")
    else:
        text = "Pregame"
    sides, score, lines = {}, {}, {}
    for t in data.get("team") or []:
        side = "H" if t.get("vh") == "H" else "V"
        sides[side] = {"name": t.get("name")}
        score[side] = one((t.get("linescore") or {}).get("score") or 0)
        out = []
        for p in t.get("player") or []:
            name = (p.get("name") or "").strip()
            if not name or name.lower() in PRESTO_SKIP or (p.get("uni") or "").upper() == "TM":
                continue
            if "," in name:
                last, _, first = (x.strip() for x in name.partition(","))
            else:
                first, _, last = name.partition(" ")
            st = p.get("stats") or {}
            out.append({"first": first, "last": last, "abbr": name, **{key: one(st.get(col)) for col, key in PT3_STATS.items()}})
        lines[side] = out
    return {"status": text.strip(), "complete": complete, "sides": sides, "score": score, "lines": lines}


def presto_page_box(page, url):
    """The box from a Presto box score page: parsed from the HTML, or, for the new template, read from the live
    update JSON the page would load (a second request to the same site). None for the XML or an empty page."""
    if page.lstrip().startswith("<?xml"):
        return None
    box = presto_box(page)
    if box is None:
        live = pt3_source(page, url)
        if live:
            box = pt3_box(get(live, as_json=True))
    return box


def read_presto_page(game, url):
    """A Presto box score page for this game, final or in progress, or None when it shows another day or game."""
    if presto_box_date(url) != date.fromisoformat(game["date"]):
        return None
    try:
        page = get(url)
    except FETCH_ERRORS:
        box = cached_box(url)  # Presto refuses the runner; the Mac's copy stands in
        if box is None:
            raise
    else:
        box = presto_page_box(page, url)
    return box if box and feed_is_game(game, box["sides"], box["lines"]) else None


def snapshot(game, box):
    """A score read from a box score page during the game, oriented to the card, for a game the browser cannot follow."""
    home, away = box["score"]["H"], box["score"]["V"]
    if should_flip(game, box["sides"], box["lines"]):
        home, away = away, home
    return {"home": home, "away": away, "status": box["status"], "at": now().isoformat(timespec="seconds")}


def is_over(game, today):
    """True once a game is BOX_PAGE_AFTER past tipoff, or, with no tipoff, once its day has passed."""
    if game.get("tip"):
        return datetime.fromisoformat(game["tip"].replace("Z", "+00:00")) < now() - BOX_PAGE_AFTER
    return date.fromisoformat(game["date"]) < today


def final_can_exist(game, today=None):
    """False while the game cannot have ended: before FINAL_EARLIEST past a known tipoff, or, with no tipoff, before
    its day. A final stored earlier came from something else (a result typed on a page's wrong row, a host's feed
    showing its earlier game, a development run), and a slate carries a final forward run after run, so the check
    runs on every build and finals pass. UW-Stevens Point vs St. Scholastica, 2026-11-07, showed a final from a
    2026-10-27 build for eleven days."""
    if game.get("tip"):
        return datetime.fromisoformat(game["tip"].replace("Z", "+00:00")) <= now() - FINAL_EARLIEST
    return date.fromisoformat(game["date"]) <= (today or now().astimezone(EASTERN).date())


def drop_final(game):
    """Forget a stored final and what was read with it."""
    game.update(final=None, newcomer_games=[], top_lines=[], box_read=False)


def box_link(game, pages):
    """The Box Score link and posted result from either team's schedule page: (link, (home, away) or None)."""
    day = date.fromisoformat(game["date"])
    exhibition = None if game.get("division") else game.get("label") == "Exhibition"
    home_row = find_row(pages.get(game["home"], []), day, game["away"], exhibition)
    away_row = find_row(pages.get(game["away"], []), day, game["home"], exhibition)
    link = next((r["links"]["boxscore"] for r in (home_row, away_row) if r and r["links"].get("boxscore")), None)
    return link or game.get("boxscore"), result_score(home_row, True) or result_score(away_row, False)


def refresh_feed(game, pages, links=None):
    """Take a live stats link a schedule page added or changed since the last full run. Schools post the link on
    game day, and a tournament host moved its second game from wbball to wbball2 in the hour before tipoff (Hope,
    2026-11-07). A new link counts when the game has no feed or when it sits on the same site as the old link, so
    another school's own stats page never replaces the host's. A link set in extra_games.json stays."""
    if (links or {}).get(game.get("id")):
        return False
    day = date.fromisoformat(game["date"])
    exhibition = None if game.get("division") else game.get("label") == "Exhibition"
    rows = (find_row(pages.get(game["home"], []), day, game["away"], exhibition),
            find_row(pages.get(game["away"], []), day, game["home"], exhibition))
    old = game.get("link")
    for url in (r["links"].get("live_stats") for r in rows if r):
        if url and url != old and (not old or not game.get("feed") or site_of(url) == site_of(old)):
            feed = live_feed(url)
            if feed and feed != game.get("feed"):
                game["feed"], game["link"] = feed, url
                return True
    return False


def read_box_page(game, url):
    """The final from a box score page a schedule links: Presto's StatCrew XML or a Sidearm HTML page."""
    day = date.fromisoformat(game["date"])
    if presto_box_date(url):
        box = read_presto_page(game, url)
        return box_result(game, box["score"]["H"], box["score"]["V"], box["sides"], box["lines"]) if box and box["complete"] else None
    box = sidearm_box(get(url))
    if not box or (box["date"] and not feed_date_matches(box["date"], day)):
        return None
    return box_result(game, box["score"]["H"], box["score"]["V"], box["sides"], box["lines"])



OFF = re.compile(r"\b(postponed|ppd|cancel+ed)\b", re.I)


def off_status(r):
    """'Postponed' or 'Canceled' when a schedule row's result column says so (Hendrix vs Rhodes, 2026-11-07), else None."""
    m = OFF.search((r or {}).get("result") or "")
    return None if not m else "Canceled" if m.group(1).lower().startswith("c") else "Postponed"


def result_score(r, page_is_home):
    """'W 70-62' or 'L, 106-26' on a schedule page -> (home, away). Pages put the winner's score first, or
    sometimes their own, so the W or L decides which score is the page team's."""
    m = re.search(r"\b([WLT])\b\s*,?\s*(\d{1,3})\s*-\s*(\d{1,3})", (r or {}).get("result") or "")
    if not m:
        return None
    a, b = int(m.group(2)), int(m.group(3))
    mine, theirs = (max(a, b), min(a, b)) if m.group(1) == "W" else (min(a, b), max(a, b)) if m.group(1) == "L" else (a, b)
    return (mine, theirs) if page_is_home else (theirs, mine)


def build_slate(day, games, schools, pages, tourn, newcomers, previous, links=None, hub=(), espn=(), others=frozenset(),
                names=None, rosters=None, hosted=None):
    prev = {g["id"]: g for g in (previous or {}).get("games", [])}
    names, rosters, hosted = names or {}, rosters or {}, hosted or {}
    keys = d3_keys(schools)
    out = []
    for g in games:
        # Games against Division I and II teams (extra_games.json can still carry them) stay off the page.
        if g.get("division"):
            continue
        gid = f'{g["date"]}-{norm(g["away"])}-at-{norm(g["home"])}'
        # A Division I host and its D3 guest often disagree on whether a game is an exhibition.
        exhibition = None if g.get("division") else g.get("label") == "Exhibition"
        home_row = find_row(pages.get(g["home"], []), day, g["away"], exhibition)
        away_row = find_row(pages.get(g["away"], []), day, g["home"], exhibition)
        listed, espn_game = find_hub(g, hub, schools, others), find_espn(g, espn, keys) if g.get("division") else None
        # Tipoff order: a D3 page, a tip set by hand in extra_games.json, the hub and ESPN (both UTC), then a
        # Division I or II host's page, whose zone is a guess.
        own = [r for t, r in ((g["home"], home_row), (g["away"], away_row)) if r and r["time"] and not schools.get(t, {}).get("extra")]
        hosts = [r for t, r in ((g["home"], home_row), (g["away"], away_row)) if r and r["time"] and schools.get(t, {}).get("extra")]
        tip, tbd = tip_time(own[0] if own else None, day)
        for later in (g.get("tip"), (listed or {}).get("tip"), (espn_game or {}).get("tip")):
            if not tip and later:
                tip, tbd = later, False
        if not tip and hosts:
            tip, tbd = tip_time(hosts[0], day)
        # Feed order: a third school's listing of the game ("A vs. B" on the host's page), then, for a neutral game,
        # either page's link to a site that is neither team's own; then the home page's live stats link, the hub's
        # link when the home school posted the listing, the home school's own Sidearm feed, the away side's links,
        # then ESPN. A school's link can point at its own idle feed (Christopher Newport's did while it played at
        # Susquehanna, 2026-11-07), so every other feed found is kept as an alternative to try after tipoff.
        home_link = (home_row or {}).get("links", {}).get("live_stats")
        away_link = (away_row or {}).get("links", {}).get("live_stats")
        hub_link = (listed or {}).get("livestats")
        hub_home = (listed or {}).get("listing_home", True)
        host_link = hosted.get(frozenset((g["home"], g["away"])), {}).get("links", {}).get("live_stats")
        feed, link = live_feed(host_link), host_link
        if not feed and g["neutral"]:
            own = [house_feed(schools.get(t)) for t in (g["home"], g["away"])]
            for u in (home_link, away_link):
                if live_feed(u) and live_feed(u) not in own:
                    feed, link = live_feed(u), u
                    break
        if not feed:
            feed, link = live_feed(home_link), home_link
        if not feed and hub_link and hub_home:
            feed, link = live_feed(hub_link), link or hub_link
        if not feed and not g["neutral"]:
            feed = house_feed(schools.get(g["home"]))
            if feed and not link:
                # Link the host's stat page, the one the feed reads, rather than the away school's.
                link = f'{re.match(r"(https?://[^/]+)", schools[g["home"]]["schedule"]).group(1)}/sidearmstats/wbball/summary'
        if not feed and hub_link and not hub_home:
            feed, away_link = live_feed(hub_link), away_link or hub_link
        if not feed:
            feed = live_feed(away_link)
        if not feed and espn_game:
            feed = espn_feed(espn_game["id"])
            link = link or f'https://www.espn.com/womens-college-basketball/game/_/gameId/{espn_game["id"]}'
        link = (links or {}).get(gid) or link or away_link
        alternatives = []
        for u in (host_link, home_link, hub_link, away_link):
            other = live_feed(u)
            if other and other != feed and other not in [a["feed"] for a in alternatives]:
                alternatives.append({"feed": other, "link": u})
        if not g["neutral"]:
            house = house_feed(schools.get(g["home"]))
            if house and house != feed and house not in [a["feed"] for a in alternatives]:
                alternatives.append({"feed": house, "link": None})
        video = (home_row or {}).get("links", {}).get("video") or (away_row or {}).get("links", {}).get("video")
        old = prev.get(gid, {})
        off = off_status(home_row) or off_status(away_row)
        final = list(g["final"]) if g.get("final") else None
        if not final and not off:
            score = result_score(home_row, True) or result_score(away_row, False)
            final = list(score) if score else old.get("final")
        entry = {
            "id": gid, "date": g["date"], "tip": tip or old.get("tip"), "tbd": tbd and not old.get("tip"),
            "home": g["home"], "away": g["away"], "neutral": g["neutral"],
            "home_rank": g.get("home_rank"), "away_rank": g.get("away_rank"), "label": g.get("label"),
            "division": g.get("division"), "d3": g.get("d3"),
            "pregame_wp": g.get("pregame_wp", 0.5), "pregame_margin": g.get("pregame_margin", 0.0),
            # False for a game no model priced (one the schedule pages added): the page then calls no result an upset.
            "modeled": g.get("modeled", True) and g.get("pregame_margin") is not None, "off": off,
            "home_lev": g.get("home_lev") or 0, "away_lev": g.get("away_lev") or 0,
            "home_tourn": round(tourn.get(g["home"], 0.0), 4), "away_tourn": round(tourn.get(g["away"], 0.0), 4),
            "feed": feed or old.get("feed"), "link": link or old.get("link"), "alt_feeds": alternatives,
            "video": video or old.get("video"),
            "final": final, "newcomer_games": old.get("newcomer_games", []),
            "boxscore": next((r["links"]["boxscore"] for r in (home_row, away_row) if r and r["links"].get("boxscore")), None) or old.get("boxscore"),
            "top_lines": old.get("top_lines", []), "box_read": old.get("box_read", False),
            "newcomers_home": newcomers.get(g["home"], []), "newcomers_away": newcomers.get(g["away"], []),
            # Every name sources use and the full roster, so a feed showing another game can be told apart.
            "home_names": names.get(g["home"], [g["home"]]), "away_names": names.get(g["away"], [g["away"]]),
            "home_roster": rosters.get(g["home"], []), "away_roster": rosters.get(g["away"], []),
        }
        if off or (entry["final"] and not final_can_exist(entry)):
            drop_final(entry)
        out.append(entry)
    return {"date": day.isoformat(), "built": now().isoformat(timespec="seconds"), "games": out}


class SchedulePages(dict):
    """Schedule rows by team, read on first use: the finals-only run reads just the pages its games need."""

    def __init__(self, schools, errors=None):
        super().__init__()
        self.schools = schools
        self.errors = errors if errors is not None else []

    def get(self, team, default=None):
        if team not in self:
            try:
                self[team] = schedule_rows(self.schools.get(team))
            except FETCH_ERRORS as exc:
                self[team] = []
                self.errors.append(f"{team} schedule: {exc}")
        return self[team] or default


def record_finals(out, today, pages, links=None):
    """For the last FINALS_DAYS_BACK days, read each game without a box score. An unfinished game first takes any
    live stats link its schedule pages added or changed since the last full run. The live feed comes first; a crew
    can reuse it for its next game, so once the game is over, the box score page a schedule links is read instead.
    A score a schedule page posts outranks a feed's. A game the browser cannot follow (no feed, but a Presto box
    score page) gets a snapshot of its score while it is on."""
    def final(g):
        try:
            return read_game(g)
        except (*FETCH_ERRORS, AttributeError, TypeError) as exc:
            # One game's odd page or feed costs that game this run, never the whole pass.
            return g, None, None, g.get("boxscore"), None, [f'{g["away"]} at {g["home"]}: {exc!r}']

    def read_game(g):
        errors, result, snap = [], None, None
        if not g.get("final"):
            try:
                refresh_feed(g, pages, links)
            except FETCH_ERRORS as exc:
                errors.append(f'{g["away"]} at {g["home"]} live stats link: {exc}')
        if g.get("feed"):
            try:
                result = read_final(g)
            except FETCH_ERRORS as exc:
                errors.append(f'{g["away"]} at {g["home"]} feed: {exc}')
        link, posted = box_link(g, pages)
        presto_link = next((u for u in (link, g.get("link")) if presto_box_date(u)), None)
        try:
            if not result and presto_link and not g.get("feed"):
                box = read_presto_page(g, presto_link)
                if box and box["complete"]:
                    result = box_result(g, box["score"]["H"], box["score"]["V"], box["sides"], box["lines"])
                elif box:
                    snap = snapshot(g, box)
            if not result and link and is_over(g, today):
                result = read_box_page(g, link)
        except FETCH_ERRORS as exc:
            errors.append(f'{g["away"]} at {g["home"]} box score: {exc}')
        if result and posted:
            result["home"], result["away"] = posted
        return g, result, posted, link, snap, errors

    for d in (today - timedelta(days=i) for i in range(FINALS_DAYS_BACK + 1)):
        path = SLATES / f"{d.isoformat()}.json"
        slate = read_json(path)
        if not slate:
            continue
        for g in slate["games"]:
            if g.get("final") and (g.get("off") or not final_can_exist(g, today)):
                drop_final(g)
        due = [g for g in slate["games"] if not g.get("box_read") and not g.get("off")
               and not (g.get("tip") and datetime.fromisoformat(g["tip"].replace("Z", "+00:00")) > now() - timedelta(minutes=10))]
        with ThreadPoolExecutor(max_workers=12) as pool:
            for g, result, posted, link, snap, errors in pool.map(final, due):
                out["errors"].extend(errors)
                g["boxscore"] = link or g.get("boxscore")
                if snap:
                    g["snapshot"] = snap
                if posted and not result:
                    g["final"] = list(posted)
                if result:
                    g["final"] = [result["home"], result["away"]]
                    g["newcomer_games"] = result["newcomers"]
                    g["top_lines"] = result["top"]
                    g["newcomers_read"] = g["box_read"] = True
                    g.pop("snapshot", None)
        path.write_text(json.dumps(slate, separators=(",", ":")))


def finals_only(previous):
    """The game-night run: finals and snapshots only, reading just the schedule pages those games need."""
    out = {**previous, "fetched_at": now().isoformat(timespec="seconds"), "errors": []}
    schools = load_schools()
    extra = read_json(EXTRA, {"schools": {}})
    for name, school in extra.get("schools", {}).items():
        schools.setdefault(name, {"team": name, "extra": True, **school})
    today = date.fromisoformat(TODAY) if TODAY else datetime.now(EASTERN).date()
    record_finals(out, today, SchedulePages(schools, out["errors"]), extra.get("links"))
    return out


def read_json(path, default=None):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def collect(previous):
    out = {"fetched_at": now().isoformat(timespec="seconds"), "errors": [], "stale": {}}
    SLATES.mkdir(parents=True, exist_ok=True)
    schools = load_schools()
    try:
        statlab_games = statlab("gameLeverages.json")
        games = statlab_games["games"]
        # Average adjusted defense / the team's own: the page multiplies it into each opposing player's game score.
        defense = statlab_games.get("defense", {})
        tourn = tournament_chance()
        newcomers = newcomers_by_team()
    except FETCH_ERRORS as exc:
        out["errors"].append(f"The D3 Stat Lab: {exc}")
        out["stale"]["statlab"] = previous.get("stale", {}).get("statlab") or previous.get("fetched_at")
        out["dates"] = previous.get("dates", {})
        return out
    extra = read_json(EXTRA, {"schools": {}, "games": []})
    names, rosters = team_names(), team_rosters()
    for name, school in extra.get("schools", {}).items():
        schools.setdefault(name, {"team": name, "extra": True, **school})
    for g in extra.get("games", []):
        margin = g.get("pregame_margin")
        if margin is not None:
            g["pregame_wp"] = round(0.5 * (1 + math.erf(margin / 11 / math.sqrt(2))), 3)
    games = games + extra.get("games", [])
    out["dates"] = {}
    for g in games:
        out["dates"][g["date"]] = out["dates"].get(g["date"], 0) + 1

    today = date.fromisoformat(TODAY) if TODAY else datetime.now(EASTERN).date()
    by_day = {}
    for g in games:
        by_day.setdefault(g["date"], []).append(g)

    # Every D3 team's schedule page, read in parallel: NPI games need tipoff and feed, and a page
    # is the only place a game against a Division I or II team shows up.
    window = [today + timedelta(days=i) for i in range(SLATE_DAYS_AHEAD + 1)]
    teams = sorted(set(schools) | {t for d in window for g in by_day.get(d.isoformat(), []) for t in (g["home"], g["away"])})
    pages = {}

    def load(team):
        try:
            return team, schedule_rows(schools.get(team)), None
        except FETCH_ERRORS as exc:
            return team, [], f"{team} schedule: {exc}"

    with ThreadPoolExecutor(max_workers=12) as pool:
        for team, rows, err in pool.map(load, teams):
            pages[team] = rows
            if err:
                out["errors"].append(err)

    members = load_members()
    ranks = {}
    for g in games:
        for side in ("home", "away"):
            if g.get(f"{side}_rank"):
                ranks[g[side]] = g[f"{side}_rank"]
    for g in extra.get("games", []):
        g["home_rank"], g["away_rank"] = g.get("home_rank") or ranks.get(g["home"]), g.get("away_rank") or ranks.get(g["away"])
    def listing(source, reader, d):
        try:
            return reader(d)
        except (*FETCH_ERRORS, TypeError, AttributeError, KeyError, IndexError) as exc:
            # A changed JSON shape costs this listing, not the run.
            out["errors"].append(f"{source} {d.isoformat()}: {exc!r}")
            return []

    resolve = opponent_resolver(schools, members)
    out["notes"] = []
    placed = place_games(games, window, pages, resolve, out["notes"])
    for d in window:
        hub = listing("Sidearm hub", hub_games, d)
        known = placed[d]
        added = page_games(d, schools, pages, known, ranks, members)
        if added:
            out["dates"][d.isoformat()] = out["dates"].get(d.isoformat(), 0) + len(added)
        path = SLATES / f"{d.isoformat()}.json"
        slate = build_slate(d, known + added, schools, pages, tourn, newcomers, read_json(path),
                            extra.get("links"), hub, (), upper_sites(members), names, rosters, host_listings(d, pages, schools))
        for g in slate["games"]:
            g["home_def"], g["away_def"] = defense.get(g["home"]), defense.get(g["away"])
        path.write_text(json.dumps(slate, separators=(",", ":")))

    record_finals(out, today, pages, extra.get("links"))
    return out


def main():
    DATA.mkdir(exist_ok=True)
    if "--presto" in sys.argv[1:]:
        out = presto_snapshot()
        print(f"[{now():%Y-%m-%d %H:%M} UTC] wrote {PRESTO_CACHE.relative_to(BASE)}: {out['pages']} schedule pages, {out['boxes']} box scores, {out['requests']} requests")
    else:
        previous = read_json(OUT, {})
        out = finals_only(previous) if "--finals" in sys.argv[1:] else collect(previous)
        OUT.write_text(json.dumps(out, indent=1))
        print(f"[{now():%Y-%m-%d %H:%M} UTC] wrote {OUT.relative_to(BASE)}")
    for note in out.get("notes") or []:
        print(f"  note: {note}")
    if out["errors"]:
        print(f"{len(out['errors'])} errors:", *out["errors"][:40], sep="\n  ", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
