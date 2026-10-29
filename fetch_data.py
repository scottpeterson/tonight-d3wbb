#!/usr/bin/env python3
"""Build each night's slate of NPI games, plus D3 games against Division I and II
teams, into data/slates/YYYY-MM-DD.json.

Rules this file enforces for every project built from the html-report template:

- One summary file, data/data.json, with `fetched_at`, `errors`, and `stale`.
  The builder reads it and the slate files, so a fetch failure can never blank the page.
- A source that fails keeps its last good value (carry forward).
- Exit 1 when any source failed, after writing the files, so the workflow log
  shows it while the site still builds.

Each run does three things:

1. Reads The D3 Stat Lab's gameLeverages.json (every scheduled game between two
   teams that count for the NPI, with preseason ranks, pregame win probability,
   and leverage), seasonSimulations.json (tournament chance), and newcomers.json.
2. For today and tomorrow (Eastern), reads every D3 team's schedule page to find
   tipoff and the live stats feed, and writes the slate. A row against a school
   that data/ncaa_members.csv lists in Division I or II becomes a game too,
   exhibitions included. Those games carry `division` and do not count for the NPI.
3. For yesterday and today, reads the feed of each game without a final score.
   When the feed reports the game complete, stores the final score and any
   newcomer's big game.
"""
import csv
import html
import json
import math
import os
import re
import sys
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
MEMBERS = DATA / "ncaa_members.csv"
SITE = json.loads((BASE / "site.json").read_text())
# The bare domain: ESPN answers 403 to this user agent when it names www.tonightind3wbb.com.
UA = {"User-Agent": f"Mozilla/5.0 ({re.sub(r'^www\.', '', SITE.get('domain') or SITE['slug'])} page builder)",
      "Accept": "text/html,application/json;q=0.9,*/*;q=0.8", "Accept-Language": "en-US,en;q=0.9"}
TAG = re.compile(r"<[^>]+>")
FETCH_ERRORS = (urllib.error.URLError, TimeoutError, ValueError, KeyError, IndexError, ET.ParseError)
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
FINALS_DAYS_BACK = 1  # yesterday and today


def now():
    return datetime.now(timezone.utc)


def get(url, as_json=False, timeout=30):
    """GET a URL with a browser-like user agent. Raises on HTTP and network errors."""
    req = urllib.request.Request(url, headers=UA)
    for attempt in (1, 2):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read()
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


# ---------------------------------------------------------------- inputs

def statlab(name):
    if STATLAB_DIR:
        return json.loads((Path(STATLAB_DIR) / name).read_text())
    return get(f"{STATLAB}/{name}", as_json=True)


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
        result_m = re.search(r'sidearm-schedule-game-result[^>]*>(.*?)</div>', b, re.S)
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


def schedule_rows(school):
    if not school or not school.get("schedule"):
        return []
    reader, url = (presto_rows, season_url(school["schedule"])) if school["type"] == "Presto" else (sidearm_rows, school["schedule"])
    # Some sites now and then serve a page with no games and a 200; one more read fixes it.
    return reader(url, school["tz"]) or reader(url, school["tz"])


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
                          "home_rank": ranks.get(home), "away_rank": ranks.get(away), "pregame_wp": 0.5, "pregame_margin": 0.0})
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
            client = re.search(r'client_shortname\s*=\s*"([^"]+)"', get(url))
            if client:
                feed = {"type": "sidearm", "url": f"https://sidearmstats.com/{client.group(1)}/{s.group(2)}/game.json"}
    except FETCH_ERRORS:
        feed = None
    _feed_cache[url] = feed
    return feed


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


def big_game(s):
    return game_score(s) >= 11 or s["pts"] >= 20 or s["reb"] >= 12 or s["ast"] >= 8 or s["blk"] >= 5 or s["stl"] >= 5


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
        team = full["Stats"][key]
        people = {p.get("PersonId"): p for p in team.get("Players") or [] if p.get("PersonId")}
        by_uni = {p.get("UniformNumber"): p for p in team.get("Players") or []}
        lines = []
        for v in team["PlayerGroups"]["Players"]["Values"]:
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
        feed_home = sides["home"]["team"].get("location") or ""
        lines = espn_lines(summary) if game["newcomers_home"] or game["newcomers_away"] else {}
    elif feed["type"] == "sidearm":
        full = get(feed["url"] + "?detail=full", as_json=True)
        g = full["Game"]
        if not sidearm_over(g) or not feed_date_matches(g.get("Date"), day):
            return None
        home_score, away_score = num(g["HomeTeam"]["Score"]), num(g["VisitingTeam"]["Score"])
        feed_home = g["HomeTeam"]["Name"]
        lines = sidearm_lines(full) if game["newcomers_home"] or game["newcomers_away"] else {}
    else:
        root = ET.fromstring(get(feed["url"]))
        venue, status = root.find(".//venue"), root.find(".//status")
        if venue is None or status is None or status.get("complete") != "Y" or not feed_date_matches(venue.get("date"), day):
            return None
        scores = {t.get("vh"): num((t.find("linescore").attrib if t.find("linescore") is not None else {}).get("score")) for t in root.iter("team")}
        home_score, away_score = scores.get("H", 0), scores.get("V", 0)
        feed_home = venue.get("homename") or ""
        lines = presto_lines(root) if game["newcomers_home"] or game["newcomers_away"] else {}
    # The feed's home side follows the stat crew; flip when the crew lists our away team as home.
    flip = len(name_tokens(feed_home) & name_tokens(game["away"])) > len(name_tokens(feed_home) & name_tokens(game["home"]))
    if flip:
        home_score, away_score = away_score, home_score
        lines = {"H": lines.get("V", []), "V": lines.get("H", [])}
    found = []
    for side, team, roster in (("H", game["home"], game["newcomers_home"]), ("V", game["away"], game["newcomers_away"])):
        for line in lines.get(side, []):
            who = match_newcomer(line, roster)
            if who and big_game(line):
                found.append({"team": team, "name": who["name"], "reason": who["reason"], "gmsc": round(game_score(line), 1),
                              "line": {k: line[k] for k in ("min", "pts", "reb", "ast", "stl", "blk", "fgm", "fga")}})
    return {"home": home_score, "away": away_score, "newcomers": sorted(found, key=lambda x: -x["gmsc"])}


# ---------------------------------------------------------------- slates

def tip_time(r, day):
    if not r or not r["time"]:
        return None, True
    hour, minute, zone = r["time"]
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=ZoneInfo(zone)).astimezone(timezone.utc).isoformat().replace("+00:00", "Z"), False


def result_score(r, page_is_home):
    """'W 70-62' on a schedule page -> (home, away)."""
    m = re.search(r"\b([WLT])\b\s*,?\s*(\d{1,3})\s*-\s*(\d{1,3})", (r or {}).get("result") or "")
    if not m:
        return None
    mine, theirs = int(m.group(2)), int(m.group(3))
    return (mine, theirs) if page_is_home else (theirs, mine)


def build_slate(day, games, schools, pages, tourn, newcomers, previous, links=None, hub=(), espn=(), others=frozenset()):
    prev = {g["id"]: g for g in (previous or {}).get("games", [])}
    keys = d3_keys(schools)
    out = []
    for g in games:
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
        # Feed order: the home page's live stats link, the hub's link when the home school posted the listing, the
        # home school's own Sidearm feed, the away side's links, then ESPN. An away school's link can point at its
        # own stat page, which shows the host's game only some of the time.
        home_link = (home_row or {}).get("links", {}).get("live_stats")
        away_link = (away_row or {}).get("links", {}).get("live_stats")
        hub_link = (listed or {}).get("livestats")
        hub_home = (listed or {}).get("listing_home", True)
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
        video = (home_row or {}).get("links", {}).get("video") or (away_row or {}).get("links", {}).get("video")
        old = prev.get(gid, {})
        final = list(g["final"]) if g.get("final") else None
        if not final:
            score = result_score(home_row, True) or result_score(away_row, False)
            final = list(score) if score else old.get("final")
        out.append({
            "id": gid, "date": g["date"], "tip": tip or old.get("tip"), "tbd": tbd and not old.get("tip"),
            "home": g["home"], "away": g["away"], "neutral": g["neutral"],
            "home_rank": g.get("home_rank"), "away_rank": g.get("away_rank"), "label": g.get("label"),
            "division": g.get("division"), "d3": g.get("d3"),
            "pregame_wp": g.get("pregame_wp", 0.5), "pregame_margin": g.get("pregame_margin", 0.0),
            "home_lev": g.get("home_lev") or 0, "away_lev": g.get("away_lev") or 0,
            "home_tourn": round(tourn.get(g["home"], 0.0), 4), "away_tourn": round(tourn.get(g["away"], 0.0), 4),
            "feed": feed or old.get("feed"), "link": link or old.get("link"),
            "video": video or old.get("video"),
            "final": final, "newcomer_games": old.get("newcomer_games", []),
            "newcomers_home": newcomers.get(g["home"], []), "newcomers_away": newcomers.get(g["away"], []),
        })
    return {"date": day.isoformat(), "built": now().isoformat(timespec="seconds"), "games": out}


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
        games = statlab("gameLeverages.json")["games"]
        tourn = tournament_chance()
        newcomers = newcomers_by_team()
    except FETCH_ERRORS as exc:
        out["errors"].append(f"The D3 Stat Lab: {exc}")
        out["stale"]["statlab"] = previous.get("stale", {}).get("statlab") or previous.get("fetched_at")
        out["dates"] = previous.get("dates", {})
        return out
    extra = read_json(EXTRA, {"schools": {}, "games": []})
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
    covered = {(g["date"], t) for g in extra.get("games", []) for t in (g["home"], g["away"])}
    # A D3 page that could not be read (Presto sites behind AWS WAF answer 405) hides that team's games against
    # Division I and II teams; ESPN lists the regular-season ones.
    blocked = {t for t in schools if not schools[t].get("extra") and not pages.get(t)}

    def listing(source, reader, d):
        try:
            return reader(d)
        except (*FETCH_ERRORS, TypeError, AttributeError, KeyError, IndexError) as exc:
            # A changed JSON shape costs this listing, not the run.
            out["errors"].append(f"{source} {d.isoformat()}: {exc!r}")
            return []

    for d in window:
        others, hosts = other_games(d, schools, pages, members, ranks, covered)
        hub, espn = listing("Sidearm hub", hub_games, d), listing("ESPN", espn_games, d)
        taken = {t for g in by_day.get(d.isoformat(), []) + others for t in (g["home"], g["away"])}
        listed, listed_hosts = listed_games(d, hub, espn, schools, members, ranks, taken, blocked)
        others += listed
        hosts.update(listed_hosts)
        new_hosts = {name: school for name, school in hosts.items() if name not in schools}
        schools.update(new_hosts)
        # Host pages fill tipoffs and live stats links. A host page that fails costs nothing, so its error is not kept.
        with ThreadPoolExecutor(max_workers=12) as pool:
            for team, rows, _err in pool.map(load, sorted(n for n in new_hosts if n not in pages)):
                pages[team] = rows
        # ESPN names a non-D1 team by its location only, so an ESPN game stays only when the host's page links the
        # D3 team's site that day.
        others = [g for g in others if g.pop("source", None) != "espn" or espn_confirmed(g, d, schools, pages)]
        if others:
            out["dates"][d.isoformat()] = out["dates"].get(d.isoformat(), 0) + len(others)
        path = SLATES / f"{d.isoformat()}.json"
        slate = build_slate(d, by_day.get(d.isoformat(), []) + others, schools, pages, tourn, newcomers, read_json(path),
                            extra.get("links"), hub, espn, upper_sites(members))
        path.write_text(json.dumps(slate, separators=(",", ":")))

    # Finals: one full-feed read per unfinished game from yesterday and today, read in parallel.
    def final(g):
        try:
            return g, read_final(g), None
        except FETCH_ERRORS as exc:
            return g, None, f'{g["away"]} at {g["home"]} feed: {exc}'

    for d in (today - timedelta(days=i) for i in range(FINALS_DAYS_BACK + 1)):
        path = SLATES / f"{d.isoformat()}.json"
        slate = read_json(path)
        if not slate:
            continue
        due = [g for g in slate["games"] if g.get("feed") and not g.get("newcomers_read")
               and not (g.get("final") and not (g["newcomers_home"] or g["newcomers_away"]))
               and not (g.get("tip") and datetime.fromisoformat(g["tip"].replace("Z", "+00:00")) > now() - timedelta(hours=2))]
        with ThreadPoolExecutor(max_workers=12) as pool:
            for g, result, err in pool.map(final, due):
                if err:
                    out["errors"].append(err)
                elif result:
                    g["final"] = [result["home"], result["away"]]
                    g["newcomer_games"] = result["newcomers"]
                    g["newcomers_read"] = True
        path.write_text(json.dumps(slate, separators=(",", ":")))
    return out


def main():
    DATA.mkdir(exist_ok=True)
    previous = read_json(OUT, {})
    out = collect(previous)
    OUT.write_text(json.dumps(out, indent=1))
    print(f"[{now():%Y-%m-%d %H:%M} UTC] wrote {OUT.relative_to(BASE)}")
    if out["errors"]:
        print(f"{len(out['errors'])} errors:", *out["errors"][:40], sep="\n  ", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
