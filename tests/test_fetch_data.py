"""Parsers in fetch_data.py, run against saved pages and feeds in tests/fixtures/."""
import json
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

import pytest

import fetch_data as f

FIX = Path(__file__).parent / "fixtures"


def rows_from(monkeypatch, reader, fixture, url, tz):
    page = (FIX / fixture).read_text()
    monkeypatch.setattr(f, "get", lambda *a, **k: page)
    return reader(url, tz)


# ---------------------------------------------------------------- times and dates

@pytest.mark.parametrize("label,expected", [
    ("7 PM", (19, 0, "America/Chicago")),
    ("7:30 PM EST", (19, 30, "America/New_York")),
    ("6:00 P.M.", (18, 0, "America/Chicago")),
    ("12 PM (PT)", (12, 0, "America/Los_Angeles")),
    ("12:15 AM", (0, 15, "America/Chicago")),
    ("TBA", None),
])
def test_parse_time(label, expected):
    assert f.parse_time(label, "America/Chicago") == expected


def test_parse_month_day_puts_spring_in_the_next_year():
    assert f.parse_month_day("Nov 14 (Sat)") == date(2026, 11, 14)
    assert f.parse_month_day("Jan. 3") == date(2027, 1, 3)
    assert f.parse_month_day("TBA") is None


def test_season_url_points_presto_paths_at_this_season():
    assert f.season_url("https://athletics.carlow.edu/sports/wbkb/2025-26/schedule") == \
        "https://athletics.carlow.edu/sports/wbkb/2026-27/schedule"


# ---------------------------------------------------------------- schedule pages

def test_sidearm_list_page(monkeypatch):
    rows = rows_from(monkeypatch, f.sidearm_rows, "sidearm_hope.html",
                     "https://athletics.hope.edu/sports/womens-basketball/schedule", "America/New_York")
    assert len(rows) == 25
    first = rows[0]
    assert first["day"] == date(2026, 11, 6)
    assert first["home"] and not first["neutral"]
    assert first["opponent"] == "University of Wisconsin-Platteville"
    assert first["links"]["live_stats"] == "https://athletics.hope.edu/sidearmstats/wbball/summary"
    assert first["links"]["video"] == "https://youtube.com/hopeathletics"
    neutral = [r for r in rows if r["neutral"]]
    assert [(r["day"], r["opponent"], r["home"]) for r in neutral] == [(date(2026, 12, 29), "Manchester University", False)]


def test_sidearm_table_page_falls_back_to_the_table_reader(monkeypatch):
    rows = rows_from(monkeypatch, f.sidearm_rows, "sidearm_table_brandywine.html",
                     "https://gounitedeast.com/schedule.aspx?schedule=3832", "America/New_York")
    assert len(rows) == 26
    away, home = rows[0], rows[2]
    assert (away["day"], away["opponent"], away["home"], away["time"]) == \
        (date(2026, 11, 11), "Neumann University", False, (18, 0, "America/New_York"))
    assert (home["day"], home["opponent"], home["home"], home["time"]) == \
        (date(2026, 11, 16), "Cairn University", True, (19, 0, "America/New_York"))
    assert not any(r["neutral"] or r["exhibition"] for r in rows)


def test_sidearm_table_reader_handles_neutral_and_results():
    page = ('<table class="sidearm-table sidearm-schedule-table"><tr><th>Date</th></tr>'
            '<tr><td>1/2/2027</td><td>vs. Wilson College</td><td>W, 70-61</td></tr>'
            '<tr><td>TBA</td><td>at Nowhere</td><td></td></tr></table>')
    rows = f.sidearm_table_rows(page, "https://x.example/schedule.aspx", "America/New_York")
    assert len(rows) == 1
    r = rows[0]
    assert (r["day"], r["opponent"], r["home"], r["neutral"], r["result"]) == \
        (date(2027, 1, 2), "Wilson College", False, True, "W, 70-61")


def test_presto_page(monkeypatch):
    # A 2025-26 page; the reader dates it in the 2026-27 season, which is fine for the structure.
    rows = rows_from(monkeypatch, f.presto_rows, "presto_willamette_2025.html",
                     "https://www.wubearcats.com/sports/wbkb/2025-26/schedule", "America/Los_Angeles")
    assert len(rows) == 27
    assert all(r["time"] for r in rows)
    exhibitions = [r["opponent"] for r in rows if r["exhibition"]]
    assert exhibitions == ["Portland", "Portland St."]
    home = next(r for r in rows if r["opponent"] == "Warner Pacific")
    assert home["home"] and home["time"] == (19, 30, "America/Los_Angeles")
    assert home["links"]["live_stats"] == "https://prestolivestats.com/tgs3oan3uncvzvyq/0l0bfk44c4a4jpst"
    assert home["links"]["video"] == "https://www.wubearcats.com/links/raf9dn"
    assert f.result_score(home, True) == (64, 48)


def test_find_row_prefers_the_named_opponent_on_a_two_game_day():
    day = date(2026, 11, 14)
    rows = [f.row(day, (13, 0, "America/New_York"), True, False, "Smith College", {}, "", ""),
            f.row(day, (15, 0, "America/New_York"), True, False, "Mount Holyoke College", {}, "", ""),
            f.row(day, (11, 0, "America/New_York"), True, False, "Exhibition: Alumni", {}, "", "")]
    assert f.find_row(rows, day, "Mt. Holyoke")["opponent"] == "Mount Holyoke College"
    assert f.find_row(rows, day, "Alumni", exhibition=True)["opponent"] == "Exhibition: Alumni"
    assert f.find_row(rows, date(2026, 11, 15), "Smith") is None


def test_live_feed_maps_links_to_feeds(monkeypatch):
    f._feed_cache.clear()
    assert f.live_feed("https://sidearmstats.com/nyu/wbball/") == \
        {"type": "sidearm", "url": "https://sidearmstats.com/nyu/wbball/game.json"}
    assert f.live_feed("https://prestolivestats.com/tgs3oan3uncvzvyq/0l0bfk44c4a4jpst") == \
        {"type": "presto", "url": "https://data.prestolivestats.com/xml/tgs3oan3uncvzvyq/events/0l0bfk44c4a4jpst.xml"}
    monkeypatch.setattr(f, "get", lambda *a, **k: 'var client_shortname = "hopeathletics";')
    assert f.live_feed("https://athletics.hope.edu/sidearmstats/wbball/summary") == \
        {"type": "sidearm", "url": "https://sidearmstats.com/hopeathletics/wbball/game.json"}
    assert f.live_feed("https://www.statbroadcast.com/events/statmonitr.php?gid=x") is None


# ---------------------------------------------------------------- box scores and newcomers

LINE = {"first": "", "last": "", "abbr": "", "min": 30, "pts": 0, "fgm": 0, "fga": 0, "ftm": 0, "fta": 0, "oreb": 0,
        "dreb": 0, "reb": 0, "ast": 0, "to": 0, "stl": 0, "blk": 0, "pf": 0}


def test_game_score_and_big_game():
    line = dict(LINE, pts=18, fgm=8, fga=14, oreb=3, dreb=3, reb=6, ast=1, to=1, stl=3, blk=2, pf=2)
    assert round(f.game_score(line), 1) == 17.7
    assert f.big_game(line)
    assert not f.big_game(dict(LINE, pts=14, fgm=6, fga=12, reb=11))
    assert f.big_game(dict(LINE, reb=12))
    assert f.big_game(dict(LINE, stl=5))
    # Olivia Corson at Eastern Illinois, 2026-10-27: game score 11.1, just over the cutoff.
    corson = dict(LINE, pts=18, fgm=5, fga=14, ftm=4, fta=4, oreb=2, dreb=2, reb=4, to=2, stl=1, blk=1, pf=2)
    assert round(f.game_score(corson), 1) == 11.1
    assert f.big_game(corson)
    assert not f.big_game(dict(corson, to=3))


def test_sidearm_lines_from_full_feed():
    full = json.loads((FIX / "sidearm_full_nyu.json").read_text())
    lines = f.sidearm_lines(full)
    assert (len(lines["H"]), len(lines["V"])) == (14, 12)
    top = max(lines["H"], key=f.game_score)
    assert (top["first"], top["last"], top["abbr"], top["pts"], top["fgm"], top["fga"], top["reb"]) == \
        ("Brooke", "Batchelor", "B. BATCHELOR", 18, 8, 14, 6)


ROSTER = [{"name": "Brooke Batchelor", "reason": "Freshman"}, {"name": "Ann Lee", "reason": "Freshman"},
          {"name": "Amy Lee", "reason": "Transfer from Hope"}]


def test_match_newcomer():
    assert f.match_newcomer(dict(LINE, first="Brooke", last="Batchelor", abbr="B. BATCHELOR"), ROSTER)["name"] == "Brooke Batchelor"
    assert f.match_newcomer(dict(LINE, abbr="B. BATCHELOR"), ROSTER)["name"] == "Brooke Batchelor"
    assert f.match_newcomer(dict(LINE, abbr="Batchelor, Brooke"), ROSTER)["name"] == "Brooke Batchelor"
    # Two newcomers share the initial and last name: no guess.
    assert f.match_newcomer(dict(LINE, abbr="A. LEE"), ROSTER) is None
    assert f.match_newcomer(dict(LINE, first="Amy", last="Lee", abbr="A. LEE"), ROSTER)["name"] == "Amy Lee"
    assert f.match_newcomer(dict(LINE, first="Zoe", last="Park", abbr="Z. PARK"), ROSTER) is None


def test_presto_lines_skip_team_rows():
    root = ET.fromstring(
        '<bbgame><team vh="H" name="Home"><player name="Lee, Ann" code="12"><stats tp="21" fgm="8" fga="15" ftm="5" fta="6" '
        'oreb="2" dreb="5" treb="7" ast="3" to="2" stl="1" blk="0" pf="2" min="31"/></player>'
        '<player name="TEAM" code="TM"><stats tp="0"/></player></team>'
        '<team vh="V" name="Away"><player name="Zoe Park" code="3"><stats tp="4" treb="2" min="20"/></player></team></bbgame>')
    lines = f.presto_lines(root)
    assert len(lines["H"]) == 1 and len(lines["V"]) == 1
    ann = lines["H"][0]
    assert (ann["first"], ann["last"], ann["pts"], ann["reb"], ann["min"]) == ("Ann", "Lee", 21, 7, 31)
    assert (lines["V"][0]["first"], lines["V"][0]["last"]) == ("Zoe", "Park")


def nyu_game(**over):
    g = {"date": "2026-02-28", "home": "NYU", "away": "Brandeis",
         "feed": {"type": "sidearm", "url": "https://sidearmstats.com/nyu/wbball/game.json"},
         "newcomers_home": [{"name": "Brooke Batchelor", "reason": "Freshman"}], "newcomers_away": []}
    g.update(over)
    return g


def test_read_final_records_score_and_newcomer(monkeypatch):
    full = json.loads((FIX / "sidearm_full_nyu.json").read_text())
    monkeypatch.setattr(f, "get", lambda *a, **k: full)
    out = f.read_final(nyu_game())
    assert (out["home"], out["away"]) == (80, 58)
    assert [(n["name"], n["gmsc"], n["line"]["pts"]) for n in out["newcomers"]] == [("Brooke Batchelor", 17.7, 18)]


def test_read_final_flips_when_the_feed_lists_our_away_team_as_home(monkeypatch):
    full = json.loads((FIX / "sidearm_full_nyu.json").read_text())
    monkeypatch.setattr(f, "get", lambda *a, **k: full)
    out = f.read_final(nyu_game(home="Brandeis", away="New York", newcomers_home=[],
                                newcomers_away=[{"name": "Brooke Batchelor", "reason": "Freshman"}]))
    assert (out["home"], out["away"]) == (58, 80)
    assert out["newcomers"][0]["team"] == "New York"


def test_read_final_ignores_another_days_game(monkeypatch):
    full = json.loads((FIX / "sidearm_full_nyu.json").read_text())
    monkeypatch.setattr(f, "get", lambda *a, **k: full)
    assert f.read_final(nyu_game(date="2026-03-01")) is None


# ---------------------------------------------------------------- Division I and II opponents

MEMBERS = {"site": {"odusports.com": {"name": "Old Dominion University", "division": 1, "site": "odusports.com"},
                    "eiupanthers.com": {"name": "Eastern Illinois University", "division": 1, "site": "eiupanthers.com"},
                    "cnusports.com": {"name": "Christopher Newport University", "division": 3, "site": "cnusports.com"}},
           "name": {}}
for _m in [*MEMBERS["site"].values(), {"name": "Wayne State University", "division": 2, "site": ""},
           {"name": "Wayne State College", "division": 2, "site": ""}, {"name": "University of Indianapolis", "division": 2, "site": "uindy.edu"}]:
    MEMBERS["name"].setdefault(f.name_key(_m["name"]), []).append(_m)


@pytest.mark.parametrize("raw,clean", [
    ("Old Dominion University (Exhibition)", "Old Dominion"),
    ("#12 Eastern Illinois", "Eastern Illinois"),
    ("at The University of Southern Mississippi", "University of Southern Mississippi"),
    ("vs. Wayne State College", "Wayne State"),
])
def test_opponent_name(raw, clean):
    assert f.opponent_name(raw) == clean


def test_opponent_division_by_site_then_by_unique_name():
    by_site = f.row(date(2026, 10, 27), None, False, False, "ODU (Exhibition)", {}, "", "", "http://www.odusports.com/")
    assert f.opponent_division(by_site, MEMBERS)[0] == 1
    by_name = f.row(date(2026, 10, 27), None, False, False, "University of Indianapolis", {}, "", "")
    assert f.opponent_division(by_name, MEMBERS)[0] == 2
    # Two members share the name key: no guess.
    assert f.opponent_division(f.row(date(2026, 10, 27), None, True, False, "Wayne State", {}, "", ""), MEMBERS) == (None, None)
    assert f.opponent_division(f.row(date(2026, 10, 27), None, True, False, "Huntington (Ind.)", {}, "", ""), MEMBERS) == (None, None)


def test_other_games_keeps_division_one_and_two_opponents_only():
    day = date(2026, 10, 27)
    pages = {
        "Christopher Newport": [
            f.row(day, (18, 30, "America/New_York"), False, False, "Old Dominion University (Exhibition)", {}, "", "", "http://www.odusports.com/"),
            f.row(date(2026, 10, 30), None, False, False, "William & Mary (Exhibition)", {}, "", "", "http://www.tribeathletics.com/")],
        "Illinois Wesleyan": [f.row(day, (18, 0, "America/Chicago"), True, False, "Christopher Newport", {}, "", "", "https://cnusports.com/")],
        "Hope": [f.row(day, (19, 0, "America/New_York"), True, False, "Indianapolis", {}, "", "")],
        "Calvin": [f.row(day, (19, 0, "America/New_York"), False, False, "Old Dominion", {}, "", "", "https://odusports.com")],
    }
    schools = {t: {"team": t, "type": "Sidearm", "schedule": "https://x.example/", "tz": "America/New_York"} for t in pages}
    games, hosts = f.other_games(day, schools, pages, MEMBERS, {"Christopher Newport": 9, "Hope": 30}, {("2026-10-27", "Calvin")})
    by_d3 = {g["d3"]: g for g in games}
    # Illinois Wesleyan's opponent is Division III; Calvin's game is covered by an extra game.
    assert set(by_d3) == {"Christopher Newport", "Hope"}
    hope = by_d3["Hope"]
    assert (hope["home"], hope["away"], hope["label"], hope["division"], hope["home_rank"]) == ("Hope", "Indianapolis", None, 2, 30)
    cnu = by_d3["Christopher Newport"]
    assert (cnu["home"], cnu["away"], cnu["label"], cnu["division"], cnu["away_rank"], cnu["home_rank"]) == \
        ("Old Dominion", "Christopher Newport", "Exhibition", 1, 9, None)
    assert hosts["Old Dominion"]["schedule"] == "https://odusports.com/sports/womens-basketball/schedule"


def test_sidearm_promotion_line_marks_an_exhibition(monkeypatch):
    page = ('<ul><li class="sidearm-schedule-game sidearm-schedule-away-game">'
            '<div class="sidearm-schedule-game-opponent-date"><span>Oct 28 (Wed)</span><span>7 PM</span></div>'
            '<div class="sidearm-schedule-game-opponent-name"><a href="http://butlersports.com" target="_blank">Butler</a></div>'
            '<span class="sidearm-schedule-game-promotion-name"> <br> Exhibition </span></li></ul>')
    monkeypatch.setattr(f, "get", lambda *a, **k: page)
    r = f.sidearm_rows("https://franklingrizzlies.com/sports/womens-basketball/schedule", "America/New_York")[0]
    assert (r["day"], r["opponent"], r["home"], r["exhibition"], r["opponent_url"]) == \
        (date(2026, 10, 28), "Butler", False, True, "http://butlersports.com")


# ---------------------------------------------------------------- host pages, the Sidearm hub, and ESPN

def test_sidearm_card_page(monkeypatch):
    rows = rows_from(monkeypatch, f.sidearm_rows, "sidearm_cards_radford.html",
                     "https://radfordathletics.com/sports/womens-basketball/schedule", "America/New_York")
    svu, bluefield = rows
    assert (svu["day"], svu["time"], svu["home"], svu["opponent"], svu["exhibition"], svu["opponent_url"], svu["links"]) == \
        (date(2026, 10, 28), (19, 0, "America/New_York"), True, "Southern Virginia", True, "https://knightathletics.com/", {})
    assert (bluefield["day"], bluefield["exhibition"]) == (date(2026, 11, 4), False)
    assert bluefield["links"] == {"video": "https://www.espn.com/watch/player/_/id/3f47c8ab-48e5-451c-9356-fd9905dab350",
                                  "live_stats": "https://radfordathletics.com/sidearmstats/wbball/summary"}


def test_find_row_with_no_exhibition_filter_takes_either_label():
    day = date(2026, 10, 28)
    rows = [f.row(day, (18, 30, "America/Chicago"), True, False, "UW-Stevens Point (Exh.)", {}, "", "exhibition")]
    assert f.find_row(rows, day, "UW-Stevens Point", False) is None
    assert f.find_row(rows, day, "UW-Stevens Point", None) is rows[0]


def test_house_feed_guesses_the_hosts_feed_without_reading_it(monkeypatch):
    # A feed answers 404 until the school's first game starts, so house_feed reads only the stats page.
    f._feed_cache.clear()
    seen = []

    def get(url, as_json=False, timeout=30):
        seen.append(url)
        return 'var client_shortname = "' + ("wmich" if "wmubroncos" in url else "wisconsin") + '";'

    monkeypatch.setattr(f, "get", get)
    host = {"type": "Sidearm", "schedule": "https://wmubroncos.com/sports/womens-basketball/schedule"}
    assert f.house_feed(host) == {"type": "sidearm", "url": "https://sidearmstats.com/wmich/wbball/game.json"}
    assert f.house_feed(dict(host, schedule="https://uwbadgers.com/sports/womens-basketball/schedule")) == \
        {"type": "sidearm", "url": "https://sidearmstats.com/wisconsin/wbball/game.json"}
    assert f.house_feed(dict(host, type="Presto")) is None
    assert all(not u.endswith("game.json") for u in seen)


HUB_SCHOOLS = {t: {"team": t, "type": "Sidearm", "schedule": f"https://{site}/sports/womens-basketball/schedule", "tz": "America/New_York"}
               for t, site in [("SUNY Geneseo", "geneseoknights.com"), ("Franklin", "franklingrizzlies.com"),
                               ("Oswego St.", "oswegolakers.com"), ("Utica", "uticapioneers.com"), ("Pacific", "goboxers.com")]}
HUB_MEMBERS = {"site": {"butlersports.com": {"name": "Butler University", "division": 1, "site": "butlersports.com"},
                        "bubearcats.com": {"name": "Binghamton University", "division": 1, "site": "bubearcats.com"},
                        "rockathletics.com": {"name": "Slippery Rock University of Pennsylvania", "division": 2, "site": "rockathletics.com"},
                        "kentstatesports.com": {"name": "Kent State University", "division": 1, "site": "kentstatesports.com"},
                        "pacifictigers.com": {"name": "University of the Pacific", "division": 1, "site": "pacifictigers.com"}},
               "name": {}}
for _m in HUB_MEMBERS["site"].values():
    HUB_MEMBERS["name"].setdefault(f.name_key(_m["name"]), []).append(_m)


def hub(monkeypatch):
    data = json.loads((FIX / "sidearm_hub.json").read_text())
    monkeypatch.setattr(f, "get", lambda *a, **k: data)
    return f.hub_games(date(2026, 10, 28))


def test_hub_games_keep_one_days_womens_basketball(monkeypatch):
    games = hub(monkeypatch)
    assert len(games) == 4  # the soccer game drops out
    geneseo = next(g for g in games if g["home"] == "SUNY Geneseo")
    assert (geneseo["tip"], geneseo["home_site"], geneseo["away_site"], geneseo["livestats"], geneseo["listing_home"]) == \
        ("2026-10-28T21:30:00Z", "knights.geneseo.edu", "binghamtonbearcats.com", "https://geneseoknights.com/sidearmstats/wbball/summary", True)
    assert next(g for g in games if g["home"] == "Oswego State")["exhibition"]  # "Scrimmage"


def test_hub_games_skip_canceled_and_malformed_listings_and_keep_tba(monkeypatch):
    data = json.loads((FIX / "sidearm_hub.json").read_text())
    wbb = [g for g in data["data"] if g["sport"]["shortname"] == "wbball"]
    canceled, broken, tba, away = (json.loads(json.dumps(g)) for g in wbb[:4])
    canceled["status"] = "C"
    broken["home_team"] = None
    tba["date_info"].update(tbd=True, datetime_utc="2026-10-28T00:00:00Z")
    away["location"]["han"] = "A"
    monkeypatch.setattr(f, "get", lambda *a, **k: {"data": [canceled, broken, tba, away]})
    games = f.hub_games(date(2026, 10, 28))
    assert [(g["home"], g["tip"], g["listing_home"]) for g in games] == [(tba["home_team"]["name"], None, True), (away["home_team"]["name"], away["date_info"]["datetime_utc"], False)]


def test_hub_matches_by_stats_link_or_name_when_sites_differ(monkeypatch):
    games = hub(monkeypatch)
    sites, keys = f.team_sites(HUB_SCHOOLS), f.d3_keys(HUB_SCHOOLS)
    teams = {g["home"]: f.hub_teams(g, sites, keys, f.upper_sites(HUB_MEMBERS)) for g in games}
    assert teams["SUNY Geneseo"] == ("SUNY Geneseo", None)       # by the live stats link's site
    assert teams["Oswego State"] == ("Oswego St.", "Utica")       # by site, then by name ("ucpioneers.com" is not ours)
    assert teams["Butler University"] == (None, "Franklin")
    assert teams["Kent State University"] == (None, None)
    # Sites only: Utica's hub site is not ours, so Utica stays unknown.
    oswego = next(g for g in games if g["home"] == "Oswego State")
    assert f.hub_teams(oswego, sites, keys, by_name=False) == ("Oswego St.", None)
    # The live stats link belongs to the school that posted the listing.
    geneseo = next(g for g in games if g["home"] == "SUNY Geneseo")
    assert f.hub_teams(dict(geneseo, listing_home=False), sites, keys, by_name=False) == (None, "SUNY Geneseo")
    # A Division I school's site rules out a name match with a D3 school of the same name.
    pacific = {"home": "Pacific", "away": "x", "home_site": "pacifictigers.com", "away_site": "", "livestats": None}
    assert f.hub_teams(pacific, sites, keys, f.upper_sites(HUB_MEMBERS)) == (None, None)


def test_listed_games_add_a_division_one_game_from_the_hub(monkeypatch):
    listing = hub(monkeypatch)
    games, hosts = f.listed_games(date(2026, 10, 28), listing, [], HUB_SCHOOLS, HUB_MEMBERS, {"SUNY Geneseo": 75}, {"Franklin"}, set())
    # Franklin already has a game; Utica's hub site is not ours; Kent State's guest is Division II.
    assert [(g["home"], g["away"], g["division"], g["d3"], g["tip"], g["home_rank"]) for g in games] == \
        [("SUNY Geneseo", "Binghamton", 1, "SUNY Geneseo", "2026-10-28T21:30:00Z", 75)]
    assert hosts == {"Binghamton": {"team": "Binghamton", "type": "Sidearm", "schedule": "https://bubearcats.com/sports/womens-basketball/schedule",
                                    "tz": "America/New_York", "extra": True}}


ESPN_SCHOOLS = {"Swarthmore": {"team": "Swarthmore", "type": "Sidearm", "schedule": "https://swarthmoreathletics.com/x", "tz": "America/New_York"}}
ESPN_MEMBERS = {"site": {}, "name": {f.name_key("University of Pennsylvania"): [{"name": "University of Pennsylvania", "division": 1, "site": "pennathletics.com"}]}}


def espn(monkeypatch):
    data = json.loads((FIX / "espn_scoreboard.json").read_text())
    monkeypatch.setattr(f, "get", lambda *a, **k: data)
    return f.espn_games(date(2026, 11, 3))


def test_espn_games_and_a_blocked_teams_game(monkeypatch):
    games = espn(monkeypatch)
    swat = next(e for e in games if e["away"]["name"] == "Swarthmore")
    assert (swat["home"], swat["away"]["d1"], swat["tip"]) == ({"name": "Pennsylvania", "d1": True}, False, "2026-11-03T23:00:00Z")
    # Only a team whose page could not be read gets games from ESPN.
    assert f.listed_games(date(2026, 11, 3), [], games, ESPN_SCHOOLS, ESPN_MEMBERS, {}, set(), set())[0] == []
    listed, hosts = f.listed_games(date(2026, 11, 3), [], games, ESPN_SCHOOLS, ESPN_MEMBERS, {}, set(), {"Swarthmore"})
    assert [(g["home"], g["away"], g["division"], g["tip"]) for g in listed] == [("Pennsylvania", "Swarthmore", 1, "2026-11-03T23:00:00Z")]
    assert hosts["Pennsylvania"]["schedule"] == "https://pennathletics.com/sports/womens-basketball/schedule"
    # A game from a schedule page finds its ESPN listing when the other team's name shares a word.
    g = {"home": "University of Pennsylvania", "away": "Swarthmore"}
    assert f.find_espn(g, games, f.d3_keys(ESPN_SCHOOLS))["id"] == swat["id"]
    assert f.find_espn(dict(g, home="Drexel"), games, f.d3_keys(ESPN_SCHOOLS)) is None


@pytest.mark.parametrize("name,key", [("Fitchburg St.", "fitchburgstate"), ("Westfield St.", "westfieldstate"),
                                      ("Centenary (LA)", "centenaryla"), ("Swarthmore", "swarthmore")])
def test_name_keys(name, key):
    assert key in f.name_keys(name)


def test_read_final_from_espn(monkeypatch):
    summary = json.loads((FIX / "espn_summary.json").read_text())
    monkeypatch.setattr(f, "get", lambda *a, **k: summary)
    game = {"date": "2026-02-14", "home": "Marquette", "away": "UConn", "feed": f.espn_feed("401825682"),
            "newcomers_home": [], "newcomers_away": [{"name": "Sarah Strong", "reason": "test"}]}
    out = f.read_final(game)
    assert (out["home"], out["away"]) == (56, 71)
    strong = next(n for n in out["newcomers"] if n["name"] == "Sarah Strong")
    assert (strong["team"], strong["line"]["pts"], strong["line"]["fgm"], strong["line"]["fga"]) == ("UConn", 22, 9, 20)


def test_hub_skips_naia_listings_and_other_states_namesakes():
    schools = {"Bethel": {"team": "Bethel", "type": "Sidearm", "schedule": "https://athletics.bethel.edu/x", "tz": "America/Chicago"},
               "Marian": {"team": "Marian", "type": "Sidearm", "schedule": "https://sabreathletics.com/x", "tz": "America/Chicago"}}
    members = {"site": {"iuhoosiers.com": {"name": "Indiana University", "division": 1, "site": "iuhoosiers.com"}},
               "name": {f.name_key("College of the Holy Cross"): [{"name": "College of the Holy Cross", "division": 1, "site": "goholycross.com"}]}}
    base = {"neutral": False, "tip": "2026-10-28T23:00:00Z", "livestats": None, "listing_home": True}
    hub = [
        # Two NAIA schools: neither the Bethel nor the Holy Cross we know.
        dict(base, home="Holy Cross College (Ind.)", home_site="hcsaints.com", away="Bethel University (Ind.)", away_site="bupilots.com",
             division="NAIA", home_id=1, away_id=2),
        # The live listings of 2026-10-28: Marian of Indiana lists its game at Indiana, and Indiana's own listing
        # names "Marian" with Marian of Wisconsin's site and school ID.
        dict(base, home="Indiana University", home_site="iuhoosiers.com", away="Marian University (Ind.)", away_site="muknights.com",
             division="NAIA", listing_home=False, home_id=68, away_id=932),
        dict(base, home="Indiana University", home_site="iuhoosiers.com", away="Marian", away_site="sabreathletics.com",
             division="DI", home_id=68, away_id=1255),
    ]
    assert f.listed_games(date(2026, 10, 28), hub[:2], [], schools, members, {}, set(), set())[0] == []
    # Indiana faces two schools that night in the hub, so its listing adds nothing.
    assert f.listed_games(date(2026, 10, 28), hub, [], schools, members, {}, set(), set())[0] == []
    # Without the conflicting listing, the same Division I listing adds the game.
    games, _ = f.listed_games(date(2026, 10, 28), hub[2:], [], schools, members, {}, set(), set())
    assert [(g["home"], g["away"]) for g in games] == [("Indiana", "Marian")]
    assert f.hub_teams(dict(hub[0], division="DI"), f.team_sites(schools), f.d3_keys(schools)) == (None, None)
    assert f.hub_name("Slippery Rock (Exhibition)") == "Slippery Rock"
    assert f.hub_name("Bethel University (Ind.)") == "Bethel (Ind.)"


def test_find_hub_needs_the_other_team_to_agree(monkeypatch):
    listing = hub(monkeypatch)
    others = f.upper_sites(HUB_MEMBERS)
    assert f.find_hub({"home": "Butler", "away": "Franklin"}, listing, HUB_SCHOOLS, others)["home"] == "Butler University"
    # Franklin's listing is against Butler, so it is not the listing of a Franklin game against someone else.
    assert f.find_hub({"home": "DePauw", "away": "Franklin"}, listing, HUB_SCHOOLS, others) is None
    naia = [dict(h, division="NAIA") for h in listing]
    assert f.find_hub({"home": "Butler", "away": "Franklin"}, naia, HUB_SCHOOLS, others) is None


def test_espn_game_stays_only_when_the_hosts_page_links_the_d3_team():
    day = date(2026, 11, 3)
    g = {"home": "Pennsylvania", "away": "Swarthmore", "d3": "Swarthmore"}
    linked = [f.row(day, (18, 0, "America/New_York"), True, False, "Swarthmore", {}, "", "", "https://swarthmoreathletics.com/")]
    other = [f.row(day, (18, 0, "America/New_York"), True, False, "Drexel", {}, "", "", "https://drexeldragons.com/")]
    assert f.espn_confirmed(g, day, ESPN_SCHOOLS, {"Pennsylvania": linked})
    assert not f.espn_confirmed(g, day, ESPN_SCHOOLS, {"Pennsylvania": other})
    assert not f.espn_confirmed(g, day, ESPN_SCHOOLS, {})


def test_sidearm_over_without_is_complete():
    game = {"IsComplete": False, "Period": 4, "ClockSeconds": 0, "Rules": {"PeriodMinutes": 10},
            "HomeTeam": {"Score": 114}, "VisitingTeam": {"Score": 26}}
    assert f.sidearm_over(game)
    assert not f.sidearm_over(dict(game, ClockSeconds=39))
    assert not f.sidearm_over(dict(game, Period=3))
    assert not f.sidearm_over(dict(game, VisitingTeam={"Score": 114}))  # tied: overtime comes next
    assert not f.sidearm_over(dict(game, ClockSeconds=None))
