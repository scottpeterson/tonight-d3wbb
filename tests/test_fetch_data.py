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
    assert hosts["Old Dominion"]["schedule"] == "https://odusports.com/"


def test_sidearm_promotion_line_marks_an_exhibition(monkeypatch):
    page = ('<ul><li class="sidearm-schedule-game sidearm-schedule-away-game">'
            '<div class="sidearm-schedule-game-opponent-date"><span>Oct 28 (Wed)</span><span>7 PM</span></div>'
            '<div class="sidearm-schedule-game-opponent-name"><a href="http://butlersports.com" target="_blank">Butler</a></div>'
            '<span class="sidearm-schedule-game-promotion-name"> <br> Exhibition </span></li></ul>')
    monkeypatch.setattr(f, "get", lambda *a, **k: page)
    r = f.sidearm_rows("https://franklingrizzlies.com/sports/womens-basketball/schedule", "America/New_York")[0]
    assert (r["day"], r["opponent"], r["home"], r["exhibition"], r["opponent_url"]) == \
        (date(2026, 10, 28), "Butler", False, True, "http://butlersports.com")
