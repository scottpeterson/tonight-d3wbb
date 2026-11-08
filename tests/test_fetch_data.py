"""Parsers in fetch_data.py, run against saved pages and feeds in tests/fixtures/."""
import json
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone
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


def test_live_feed_reads_a_hosts_client_once(monkeypatch):
    f._feed_cache.clear()
    f._client_cache.clear()
    calls = []

    def get(url, as_json=False, timeout=30):
        calls.append(url)
        return 'var client_shortname = "hopecollege";'

    monkeypatch.setattr(f, "get", get)
    assert f.live_feed("https://athletics.hope.edu/sidearmstats/wbball/summary")["url"] == "https://sidearmstats.com/hopecollege/wbball/game.json"
    assert f.live_feed("https://athletics.hope.edu/sidearmstats/wbball2/summary")["url"] == "https://sidearmstats.com/hopecollege/wbball2/game.json"
    assert calls == ["https://athletics.hope.edu/sidearmstats/wbball/summary"]


def test_sibling_feeds_name_the_hosts_other_courts():
    one = {"type": "sidearm", "url": "https://sidearmstats.com/hopecollege/wbball/game.json"}
    two = {"type": "sidearm", "url": "https://sidearmstats.com/hopecollege/wbball2/game.json"}
    assert [x["url"] for x in f.sibling_feeds(one)] == \
        ["https://sidearmstats.com/hopecollege/wbball2/game.json", "https://sidearmstats.com/hopecollege/wbball3/game.json"]
    assert [x["url"] for x in f.sibling_feeds(two)] == \
        ["https://sidearmstats.com/hopecollege/wbball/game.json", "https://sidearmstats.com/hopecollege/wbball3/game.json"]
    assert f.sibling_feeds({"type": "presto", "url": "https://data.prestolivestats.com/xml/a/events/b.xml"}) == []
    assert f.sibling_feeds(None) == []
    assert f.sibling_link("https://athletics.hope.edu/sidearmstats/wbball/summary", two) == "https://athletics.hope.edu/sidearmstats/wbball2/summary"
    assert f.sibling_link("https://www.youtube.com/hopeathletics", two) == "https://www.youtube.com/hopeathletics"
    assert f.sibling_link(None, two) is None


def test_read_final_adopts_the_hosts_other_feed(monkeypatch):
    # Hope's Michele Schoon Tournament, 2026-11-07: the slate named wbball, where Hope's own game sat unstarted,
    # while the game ran on wbball2. The pass adopts wbball2 and reads the final there.
    full = json.loads((FIX / "sidearm_full_nyu.json").read_text())
    idle = {"Game": {"HasStarted": False, "IsComplete": False, "Date": full["Game"]["Date"],
                     "HomeTeam": {"Name": "Hope", "Id": "TB", "Score": 0}, "VisitingTeam": {"Name": "Illinois Wesleyan", "Id": "TA", "Score": 0}}}
    calls = []

    def get(url, as_json=False, timeout=30):
        calls.append(url)
        return full if "/wbball2/" in url else idle

    monkeypatch.setattr(f, "get", get)
    game = nyu_game(link="https://gonyuathletics.com/sidearmstats/wbball/summary")
    out = f.read_final(game)
    assert (out["home"], out["away"]) == (80, 58)
    assert game["feed"]["url"] == "https://sidearmstats.com/nyu/wbball2/game.json"
    assert game["link"] == "https://gonyuathletics.com/sidearmstats/wbball2/summary"
    # The primary's full read, one small read of the sibling, then the sibling's full read.
    assert calls == ["https://sidearmstats.com/nyu/wbball/game.json?detail=full", "https://sidearmstats.com/nyu/wbball2/game.json",
                     "https://sidearmstats.com/nyu/wbball2/game.json?detail=full"]
    # No sibling shows the game: nothing changes.
    monkeypatch.setattr(f, "get", lambda *a, **k: idle)
    game = nyu_game()
    assert f.read_final(game) is None and game["feed"]["url"].endswith("/wbball/game.json")


def test_refresh_feed_takes_a_link_a_page_added_on_game_day(monkeypatch):
    f._feed_cache.clear()
    f._client_cache.clear()
    monkeypatch.setattr(f, "get", lambda url, *a, **k: 'var client_shortname = "' + ("hopecollege" if "hope.edu" in url else "owu") + '";')
    day = date(2026, 11, 7)
    game = {"id": "2026-11-07-ohiowesleyan-at-uwplatteville", "date": "2026-11-07", "home": "UW-Platteville", "away": "Ohio Wesleyan",
            "link": "https://athletics.hope.edu/sidearmstats/wbball/summary",
            "feed": {"type": "sidearm", "url": "https://sidearmstats.com/hopecollege/wbball/game.json"}}
    moved = {"UW-Platteville": [f.row(day, (12, 0, "America/Chicago"), False, True, "Ohio Wesleyan",
                                      {"live_stats": "https://athletics.hope.edu/sidearmstats/wbball2/summary"}, "", "")]}
    assert f.refresh_feed(game, moved)
    assert game["feed"]["url"] == "https://sidearmstats.com/hopecollege/wbball2/game.json"
    assert game["link"] == "https://athletics.hope.edu/sidearmstats/wbball2/summary"
    # The same link again: no change. Another school's own stats page does not replace the host's.
    assert not f.refresh_feed(game, moved)
    own = {"Ohio Wesleyan": [f.row(day, (13, 0, "America/New_York"), False, True, "UW-Platteville",
                                   {"live_stats": "https://battlingbishops.com/sidearmstats/wbball/summary"}, "", "")]}
    assert not f.refresh_feed(game, own)
    # A game with no feed takes the first link a page offers.
    bare = {k: v for k, v in game.items() if k not in ("link", "feed")}
    assert f.refresh_feed(bare, own) and bare["feed"]["url"] == "https://sidearmstats.com/owu/wbball/game.json"
    # A link set by hand in extra_games.json stays.
    pinned = {k: v for k, v in game.items() if k != "feed"}
    assert not f.refresh_feed(pinned, moved, {game["id"]: "http://stats.statbroadcast.com/x"})


# ---------------------------------------------------------------- box scores and newcomers

LINE = {"first": "", "last": "", "abbr": "", "min": 30, "pts": 0, "fgm": 0, "fga": 0, "ftm": 0, "fta": 0, "oreb": 0,
        "dreb": 0, "reb": 0, "ast": 0, "to": 0, "stl": 0, "blk": 0, "pf": 0}


def test_game_score_and_played():
    line = dict(LINE, pts=18, fgm=8, fga=14, oreb=3, dreb=3, reb=6, ast=1, to=1, stl=3, blk=2, pf=2)
    assert round(f.game_score(line), 1) == 17.7
    # Olivia Corson at Eastern Illinois, 2026-10-27: game score 11.1.
    corson = dict(LINE, pts=18, fgm=5, fga=14, ftm=4, fta=4, oreb=2, dreb=2, reb=4, to=2, stl=1, blk=1, pf=2)
    assert round(f.game_score(corson), 1) == 11.1
    assert f.played(corson)
    assert not f.played(dict(LINE, min=0))
    assert f.played(dict(LINE, min=0, pf=1))  # a crew that leaves minutes blank
    assert f.played(dict(LINE, min=3))


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
    # The top list covers every player in the game, best first, at most 15 per team.
    top = out["top"]
    assert 0 < len(top) and all(sum(x["team"] == t for x in top) <= f.TOP_N for t in ("NYU", "Brandeis"))
    assert [x["gmsc"] for x in top] == sorted((x["gmsc"] for x in top), reverse=True)
    assert top[0]["gmsc"] >= 17.7 and {x["team"] for x in top} <= {"NYU", "Brandeis"}


def test_read_final_records_the_top_list_with_no_newcomers(monkeypatch):
    full = json.loads((FIX / "sidearm_full_nyu.json").read_text())
    monkeypatch.setattr(f, "get", lambda *a, **k: full)
    out = f.read_final(nyu_game(newcomers_home=[]))
    assert out["newcomers"] == [] and len(out["top"]) > f.TOP_N


def test_read_final_flips_when_the_feed_lists_our_away_team_as_home(monkeypatch):
    full = json.loads((FIX / "sidearm_full_nyu.json").read_text())
    monkeypatch.setattr(f, "get", lambda *a, **k: full)
    out = f.read_final(nyu_game(home="Brandeis", away="New York", newcomers_home=[],
                                newcomers_away=[{"name": "Brooke Batchelor", "reason": "Freshman"}]))
    assert (out["home"], out["away"]) == (58, 80)
    assert out["newcomers"][0]["team"] == "New York"


@pytest.mark.parametrize("line,name", [({"first": "Jane", "last": "Doe", "abbr": "J. Doe"}, "Jane Doe"),
                                       ({"first": "", "last": "", "abbr": "DOE,JANE"}, "Jane Doe"),
                                       ({"first": "", "last": "", "abbr": "McDonald, Ann-Marie"}, "Ann-Marie McDonald")])
def test_line_name(line, name):
    assert f.line_name(line) == name


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


def test_should_flip_trusts_team_code_over_swapped_names():
    game = {"home": "Medgar Evers", "away": "St. Joseph's Long Island", "newcomers_home": [], "newcomers_away": []}
    swapped = {"H": {"name": "St. Joseph's Long Island", "id": "MEDGAR"}, "V": {"name": "Medgar Evers", "id": "SJLI"}}
    assert not f.should_flip(game, swapped, {})
    crew_home = {"H": {"name": "St. Joseph's Long Island", "id": "SJLI"}, "V": {"name": "Medgar Evers", "id": "MEDGAR"}}
    assert f.should_flip(game, crew_home, {})


def test_should_flip_counts_roster_players_first():
    roster = [{"name": "Ann Lee", "reason": "FR"}, {"name": "Bea Cole", "reason": "TR"}]
    game = {"home": "Calvin", "away": "Hope", "newcomers_home": roster, "newcomers_away": []}
    lines = [{"first": n.split()[0], "last": n.split()[1], "abbr": n} for n in ("Ann Lee", "Bea Cole")]
    sides = {"H": {"name": "Calvin", "id": "CALV"}, "V": {"name": "Hope", "id": "HOPE"}}
    # Names and codes say keep (3 each side); two Calvin newcomers on the visiting side say flip.
    assert f.should_flip(game, sides, {"H": [], "V": lines})
    assert not f.should_flip(game, sides, {"H": lines, "V": []})


# Fredonia 71, Thiel 44 (2025-11-07): a Sidearm box score page, the permanent record once a feed moves on.
BOX_GAME = {"date": "2025-11-07", "home": "Fredonia St.", "away": "Thiel", "neutral": False, "tip": "2025-11-08T00:00:00Z",
            "newcomers_home": [], "newcomers_away": [{"name": "Issy Green", "reason": "FR"}]}


def box_page():
    return (Path(__file__).parent / "fixtures" / "sidearm_boxscore.html").read_text()


def test_sidearm_box_page():
    box = f.sidearm_box(box_page())
    assert box["date"] == "11/7/2025"
    assert box["sides"] == {"V": {"name": "Thiel", "id": "THI"}, "H": {"name": "Fredonia", "id": "Fred"}}
    assert box["score"] == {"V": 44, "H": 71}
    green = box["lines"]["V"][0]
    assert (green["first"], green["last"], green["min"], green["pts"], green["fgm"], green["fga"], green["ftm"], green["fta"],
            green["oreb"], green["dreb"], green["reb"], green["ast"], green["to"], green["stl"], green["pf"]) == (
            "Issy", "Green", 33, 14, 4, 9, 5, 10, 0, 4, 4, 3, 5, 5, 1)
    assert all(line["last"] != "TEAM" for side in "VH" for line in box["lines"][side])
    assert sum(line["pts"] for line in box["lines"]["H"]) == 71


def test_read_box_page_orients_and_finds_newcomers(monkeypatch):
    monkeypatch.setattr(f, "get", lambda *a, **k: box_page())
    result = f.read_box_page(BOX_GAME, "https://fredoniabluedevils.com/sports/womens-basketball/stats/2025-26/thiel-college/boxscore/9019")
    assert (result["home"], result["away"]) == (71, 44)
    assert [(n["team"], n["name"], n["line"]["pts"]) for n in result["newcomers"]] == [("Thiel", "Issy Green", 14)]
    assert {x["team"] for x in result["top"]} == {"Fredonia St.", "Thiel"} and result["top"][0]["gmsc"] >= result["top"][-1]["gmsc"]
    # The page's date has to be the game's.
    assert f.read_box_page({**BOX_GAME, "date": "2025-11-08"}, "https://x/boxscore/1") is None


def test_box_link_and_posted_result_from_either_page():
    day = date(2025, 11, 7)
    away_row = {"day": day, "exhibition": False, "opponent": "Fredonia", "result": "L, 44-71",
                "links": {"boxscore": "https://thiel.example/boxscore/1"}}
    link, posted = f.box_link(BOX_GAME, {"Thiel": [away_row]})
    assert link == "https://thiel.example/boxscore/1" and posted == (71, 44)
    assert f.box_link({**BOX_GAME, "boxscore": "https://saved/1"}, {}) == ("https://saved/1", None)


def test_is_over(monkeypatch):
    monkeypatch.setattr(f, "now", lambda: datetime(2025, 11, 8, 2, 0, tzinfo=timezone.utc))
    assert not f.is_over(BOX_GAME, date(2025, 11, 7))
    monkeypatch.setattr(f, "now", lambda: datetime(2025, 11, 8, 2, 31, tzinfo=timezone.utc))
    assert f.is_over(BOX_GAME, date(2025, 11, 7))
    assert f.is_over({"date": "2025-11-06"}, date(2025, 11, 7)) and not f.is_over({"date": "2025-11-07"}, date(2025, 11, 7))


def test_result_score_reads_the_page_teams_side_from_w_or_l():
    # Centenary's page at ULM, 2026-11-05: winner's score first.
    assert f.result_score({"result": "L , 106-26"}, False) == (106, 26)
    assert f.result_score({"result": "L 62-70"}, True) == (62, 70)
    assert f.result_score({"result": "W, 71-44"}, True) == (71, 44)
    assert f.result_score({"result": "W 44-71"}, False) == (44, 71)
    assert f.result_score({"result": ""}, True) is None


# St. Joseph's Brooklyn's crew ran one feed for its whole tournament, 2026-11-06: Pratt at St. Joseph's Brooklyn,
# then St. Joseph's Long Island vs Medgar Evers, with the names typed on the wrong sides.
def tourney_game(home, away):
    names, rosters = f.team_names(), f.team_rosters()
    return {"home": home, "away": away, "home_names": names[home], "away_names": names[away],
            "home_roster": rosters[home], "away_roster": rosters[away], "newcomers_home": [], "newcomers_away": []}


def box_lines(team, n):
    return [{"first": p.split()[0], "last": p.split()[-1], "abbr": p} for p in f.team_rosters()[team][:n]]


TOURNEY_SIDES = {"H": {"name": "St. Joseph's Long Island", "id": "MEDGAR"}, "V": {"name": "Medgar Evers", "id": "SJLI"}}


def test_feed_from_another_tournament_game_is_rejected():
    lines = {"H": box_lines("Medgar Evers", 8), "V": box_lines("St. Joseph's Long Island", 9)}
    assert f.feed_is_game(tourney_game("Medgar Evers", "St. Joseph's Long Island"), TOURNEY_SIDES, lines)
    assert not f.feed_is_game(tourney_game("St. Joseph's Brooklyn", "Pratt"), TOURNEY_SIDES, lines)


def test_without_players_the_names_and_codes_decide():
    assert f.feed_is_game(tourney_game("Medgar Evers", "St. Joseph's Long Island"), TOURNEY_SIDES, {})
    # "St. Joseph's Long Island" shares only generic words with St. Joseph's Brooklyn's names.
    assert not f.feed_is_game(tourney_game("St. Joseph's Brooklyn", "Pratt"), TOURNEY_SIDES, {})
    # A source's longer name still matches: Wis.-Platteville, University of Wisconsin-Platteville.
    game = tourney_game("UW-Platteville", "Hope")
    assert f.feed_is_game(game, {"H": {"name": "Wisconsin-Platteville"}, "V": {"name": "Hope College"}}, {})


def test_a_team_with_no_player_on_the_feed_is_not_playing():
    # Principia's tournament, 2026-11-07: the host's feed showed Aurora vs Westminster (MO). Aurora's players alone
    # made it count for the phantom "Aurora at Principia" too, so both lists showed each Aurora line twice.
    lines = {"H": box_lines("Aurora", 8), "V": box_lines("Westminster (MO)", 7)}
    sides = {"H": {"name": "Aurora"}, "V": {"name": "Westminster"}}
    assert f.feed_is_game(tourney_game("Aurora", "Westminster (MO)"), sides, lines)
    assert not f.feed_is_game(tourney_game("Principia", "Aurora"), sides, lines)
    # One side's lines missing: the rule waits for both sides.
    assert f.feed_is_game(tourney_game("Principia", "Aurora"), sides, {"H": box_lines("Aurora", 8)})


def test_players_outrank_names():
    # Right names, wrong players: the crew left the last game's teams on the feed.
    sides = {"H": {"name": "St. Joseph's Brooklyn"}, "V": {"name": "Pratt"}}
    lines = {"H": box_lines("Medgar Evers", 8), "V": box_lines("St. Joseph's Long Island", 9)}
    assert not f.feed_is_game(tourney_game("St. Joseph's Brooklyn", "Pratt"), sides, lines)
    # A roster not published yet (fewer than five players listed) leaves it to the names.
    game = {**tourney_game("St. Joseph's Brooklyn", "Pratt"), "home_roster": ["A B"], "away_roster": []}
    assert f.feed_is_game(game, sides, lines)


# Eastern Connecticut St. 95, Lasell 72 (2026-11-06): a Presto box score page. The first visiting row is rewritten
# in Eureka's template ("25 - Nudd,Marissa - F", name marked .player-name).
PRESTO_URL = "https://laserpride.lasell.edu/sports/wbkb/2026-27/boxscores/20261106_h03q.xml"


def presto_page():
    return (Path(__file__).parent / "fixtures" / "presto_boxscore.html").read_text()


def test_presto_box_page():
    box = f.presto_box(presto_page())
    assert (box["status"], box["complete"]) == ("Final", True)
    assert box["sides"] == {"V": {"name": "Eastern Connecticut"}, "H": {"name": "Lasell"}}
    assert box["score"] == {"V": 95, "H": 72}
    nudd = box["lines"]["V"][0]
    assert (nudd["first"], nudd["last"], nudd["min"], nudd["pts"], nudd["fgm"], nudd["fga"], nudd["ftm"], nudd["fta"],
            nudd["oreb"], nudd["dreb"], nudd["reb"], nudd["ast"]) == ("Marissa", "Nudd", 37, 27, 10, 19, 6, 7, 3, 4, 7, 3)
    assert box["lines"]["H"][0]["first"] == "Bri" and box["lines"]["H"][0]["last"] == "Franklin"
    assert not any(line["last"].lower() in ("team", "totals") or line["first"].upper() == "STARTERS"
                   for side in "VH" for line in box["lines"][side])


def test_read_box_page_reads_presto_html_and_dates_it_by_the_link(monkeypatch):
    monkeypatch.setattr(f, "get", lambda *a, **k: presto_page())
    game = {"date": "2026-11-06", "home": "Lasell", "away": "Eastern Connecticut St.", "newcomers_home": [], "newcomers_away": []}
    result = f.read_box_page(game, PRESTO_URL)
    assert (result["home"], result["away"]) == (72, 95)
    assert result["top"][0]["team"] == "Eastern Connecticut St."
    assert f.presto_box_date(PRESTO_URL) == date(2026, 11, 6)
    assert f.read_box_page({**game, "date": "2026-11-07"}, PRESTO_URL) is None


def test_snapshot_orients_a_live_presto_score(monkeypatch):
    monkeypatch.setattr(f, "now", lambda: datetime(2026, 11, 7, 1, 0, tzinfo=timezone.utc))
    box = f.presto_box(presto_page())
    box["status"], box["complete"] = "3rd Quarter", False
    game = {"home": "Lasell", "away": "Eastern Connecticut St.", "newcomers_home": [], "newcomers_away": []}
    assert f.snapshot(game, box) == {"home": 72, "away": 95, "status": "3rd Quarter", "at": "2026-11-07T01:00:00+00:00"}


def test_a_cut_off_read_costs_one_game_not_the_finals_pass(monkeypatch, tmp_path):
    import http.client
    monkeypatch.setattr(f, "SLATES", tmp_path)
    monkeypatch.setattr(f, "now", lambda: datetime(2026, 11, 7, 5, 0, tzinfo=timezone.utc))
    base = {"date": "2026-11-06", "tip": "2026-11-07T00:00:00Z", "neutral": False, "newcomers_home": [], "newcomers_away": []}
    games = [{**base, "id": "a", "home": "A", "away": "B", "feed": {"type": "sidearm", "url": "https://sidearmstats.com/a/wbball/game.json"}},
             {**base, "id": "c", "home": "C", "away": "D", "final": [70, 60], "box_read": True}]
    (tmp_path / "2026-11-06.json").write_text(json.dumps({"date": "2026-11-06", "games": games}))

    def cut_off(*a, **k):
        raise http.client.IncompleteRead(b"x", 10)
    monkeypatch.setattr(f, "get", cut_off)
    out = {"errors": []}
    f.record_finals(out, date(2026, 11, 7), {})
    assert len(out["errors"]) == 1 and "IncompleteRead" in out["errors"][0]
    assert json.loads((tmp_path / "2026-11-06.json").read_text())["games"][1]["final"] == [70, 60]


def test_a_final_the_game_cannot_have_yet_is_dropped(monkeypatch, tmp_path):
    # UW-Stevens Point vs St. Scholastica, 2026-11-07: a final from a 2026-10-27 build rode along in every slate
    # until the game day. A build and a finals pass both drop a final that predates 45 minutes after tipoff.
    monkeypatch.setattr(f, "now", lambda: datetime(2026, 11, 7, 17, 0, tzinfo=timezone.utc))
    old = {"id": "2026-11-07-uwstevenspoint-at-stscholastica", "tip": "2026-11-07T19:00:00Z", "final": [64, 53],
           "top_lines": [{"team": "St. Norbert"}], "newcomer_games": [], "box_read": True}
    game = {"date": "2026-11-07", "home": "St. Scholastica", "away": "UW-Stevens Point", "neutral": True}
    built = f.build_slate(date(2026, 11, 7), [game], {}, {}, {}, {}, {"games": [old]})["games"][0]
    assert (built["final"], built["top_lines"], built["box_read"], built["tip"]) == (None, [], False, "2026-11-07T19:00:00Z")
    # The same carried final counts once the game can be over, and a game with no tipoff keeps its final on its day.
    monkeypatch.setattr(f, "now", lambda: datetime(2026, 11, 7, 19, 45, tzinfo=timezone.utc))
    assert f.build_slate(date(2026, 11, 7), [game], {}, {}, {}, {}, {"games": [old]})["games"][0]["final"] == [64, 53]
    assert f.final_can_exist({"date": "2026-11-07"}, date(2026, 11, 7)) and not f.final_can_exist({"date": "2026-11-08"}, date(2026, 11, 7))

    monkeypatch.setattr(f, "SLATES", tmp_path)
    monkeypatch.setattr(f, "now", lambda: datetime(2026, 11, 7, 17, 0, tzinfo=timezone.utc))
    slate_game = {**old, "date": "2026-11-07", "home": "St. Scholastica", "away": "UW-Stevens Point", "neutral": True,
                  "newcomers_home": [], "newcomers_away": []}
    (tmp_path / "2026-11-07.json").write_text(json.dumps({"date": "2026-11-07", "games": [slate_game]}))
    f.record_finals({"errors": []}, date(2026, 11, 7), {})
    written = json.loads((tmp_path / "2026-11-07.json").read_text())["games"][0]
    assert written["final"] is None and written["box_read"] is False


def test_page_games_add_a_d3_game_the_stat_lab_list_lacks():
    # Hope vs Illinois Wesleyan on 2026-11-07: a tournament's second day, TBA on the pages until the first day ended,
    # so gameLeverages.json did not list it. Both pages list it now; the pair joins once.
    day = date(2026, 11, 7)
    pages = {
        "Hope": [f.row(day, (15, 0, "America/New_York"), True, False, "Illinois Wesleyan University", {}, "", "", "https://www.iwusports.com/")],
        "Illinois Wesleyan": [f.row(day, (14, 0, "America/Chicago"), False, False, "Hope College", {}, "", "", "https://athletics.hope.edu/")],
        # A Division II opponent by name, and an exhibition, stay out.
        "Calvin": [f.row(day, (19, 0, "America/New_York"), True, False, "Indianapolis", {}, "", "")],
        "Ohio Wesleyan": [f.row(day, (13, 0, "America/New_York"), False, True, "Calvin (Exhibition)", {}, "", "")],
        # A placeholder row that links the host's site, and a host's listing of another game, name no opponent.
        "Benedictine": [f.row(day, (12, 0, "America/Chicago"), False, True, "WashU Tournament", {}, "", "", "http://washubears.com/")],
        "WashU": [f.row(day, (12, 0, "America/Chicago"), False, True, "Benedictine (Ill.) vs. Central College", {}, "", "")],
        # A neutral row whose link points at the tournament host (Principia) names a Westminster, not the host.
        "Aurora": [f.row(day, (14, 0, "America/Chicago"), False, True, "Westminster University", {}, "", "", "http://principiaathletics.com")],
        "Principia": [], "Westminster (MO)": [], "Westminster (PA)": [],
    }
    schools = {t: {"team": t, "type": "Sidearm", "schedule": f"https://{t.lower().replace(' ', '')}.example/", "tz": "America/New_York"} for t in pages}
    schools["Hope"]["schedule"] = "https://athletics.hope.edu/sports/womens-basketball/schedule"
    schools["Illinois Wesleyan"]["schedule"] = "https://www.iwusports.com/sports/womens-basketball/schedule"
    schools["WashU"]["schedule"] = "https://washubears.com/sports/womens-basketball/schedule"
    schools["Principia"]["schedule"] = "https://principiaathletics.com/sports/womens-basketball/schedule"
    ranks = {"Hope": 6, "Illinois Wesleyan": 41}
    games = f.page_games(day, schools, pages, [], ranks, MEMBERS)
    assert [(g["home"], g["away"], g["neutral"], g["home_rank"], g["away_rank"], g["pregame_wp"]) for g in games] == \
        [("Hope", "Illinois Wesleyan", False, 6, 41, 0.5)]
    # A game the Stat Lab already lists is not added again.
    assert f.page_games(day, schools, pages, [{"home": "Hope", "away": "Illinois Wesleyan"}], ranks, MEMBERS) == []


# ---------------------------------------------------------------- postponed games, projected pairings

HENDRIX_ROW = """<li class="sidearm-schedule-game sidearm-schedule-home-game sidearm-schedule-game-completed">
<div class="sidearm-schedule-game-row"><div class="sidearm-schedule-game-details"><div>
<span class="sidearm-schedule-game-opponent-date flex-item-1"><span>Nov 7 (Sat)</span></span><span>/</span>
<span class="sidearm-schedule-game-result-final">Final</span></div></div>
<div class="sidearm-schedule-game-opponent-text"><span class="sidearm-schedule-game-opponent-name">
<a aria-label="Rhodes College on November 7 1:00 PM" href="http://www.rhodeslynx.com/">Rhodes College</a></span></div>
<div class="sidearm-schedule-game-result "><span>Postponed</span></div></div></li>"""


def test_sidearm_result_reads_postponed_not_the_final_label(monkeypatch):
    # Hendrix vs Rhodes, 2026-11-07: the row carries a "...-result-final">Final</span> before the result "Postponed".
    monkeypatch.setattr(f, "get", lambda *a, **k: HENDRIX_ROW)
    r = f.sidearm_rows("https://hendrixwarriors.com/sports/womens-basketball/schedule", "America/Chicago")[0]
    assert (r["opponent"], r["result"]) == ("Rhodes College", "Postponed")
    assert f.off_status(r) == "Postponed"
    assert f.off_status({"result": "Cancelled"}) == "Canceled" and f.off_status({"result": "W, 70-62"}) is None


def test_a_postponed_game_shows_no_final_and_the_finals_pass_skips_it(monkeypatch, tmp_path):
    day = date(2026, 11, 7)
    pages = {"Hendrix": [f.row(day, (13, 0, "America/Chicago"), True, False, "Rhodes College", {}, "Postponed", "")]}
    game = {"date": "2026-11-07", "home": "Hendrix", "away": "Rhodes", "neutral": False, "pregame_margin": 18.0, "pregame_wp": 0.949}
    old = {"id": "2026-11-07-rhodes-at-hendrix", "final": [70, 60], "box_read": True, "top_lines": [{"team": "Hendrix"}], "newcomer_games": []}
    built = f.build_slate(day, [game], {}, pages, {}, {}, {"games": [old]})["games"][0]
    assert (built["off"], built["final"], built["box_read"], built["modeled"]) == ("Postponed", None, False, True)
    # The finals pass reads nothing for it, and drops a final it still carries.
    monkeypatch.setattr(f, "SLATES", tmp_path)
    monkeypatch.setattr(f, "get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("read a postponed game")))
    slate_game = {**built, "feed": {"type": "sidearm", "url": "https://sidearmstats.com/hendrix/wbball/game.json"}, "final": [70, 60],
                  "newcomers_home": [], "newcomers_away": []}
    (tmp_path / "2026-11-07.json").write_text(json.dumps({"date": "2026-11-07", "games": [slate_game]}))
    out = {"errors": []}
    f.record_finals(out, day, {})
    written = json.loads((tmp_path / "2026-11-07.json").read_text())["games"][0]
    assert out["errors"] == [] and written["final"] is None


def test_page_games_are_unmodeled_and_stat_lab_games_are_modeled():
    day = date(2026, 11, 7)
    added = {"date": "2026-11-07", "home": "UW-Platteville", "away": "Ohio Wesleyan", "neutral": True, "pregame_wp": 0.5,
             "pregame_margin": 0.0, "modeled": False}
    priced = {"date": "2026-11-07", "home": "Roanoke", "away": "William Peace", "neutral": False, "pregame_wp": 0.59, "pregame_margin": 2.5}
    built = f.build_slate(day, [added, priced], {}, {}, {}, {}, {})["games"]
    assert [g["modeled"] for g in built] == [False, True]


def widener_pages():
    day = date(2026, 11, 7)
    return {
        "Salisbury": [f.row(day, (15, 0, "America/New_York"), False, True, "Widener", {}, "L, 60-85", "", "https://widenerpride.com/")],
        "Marywood": [f.row(day, None, False, True, "Centenary University", {}, "Final", "", "https://centenarycyclones.com/")],
        "Widener": [f.row(day, None, True, False, "Centenary vs Marywood", {}, "Final", ""),
                    f.row(day, None, True, False, "Salisbury", {}, "Final", "", "https://suseagulls.com/")],
        "Centenary (NJ)": [f.row(day, (13, 0, "America/New_York"), False, True, "Marywood University", {}, "L, 49-70", "", "https://marywoodpacers.com/")],
    }


WIDENER_SCHOOLS = {t: {"team": t, "type": "Sidearm", "schedule": f"https://{s}/sports/womens-basketball/schedule", "tz": "America/New_York"}
                   for t, s in (("Salisbury", "suseagulls.com"), ("Marywood", "marywoodpacers.com"), ("Widener", "widenerpride.com"),
                                ("Centenary (NJ)", "centenarycyclones.com"))}


def test_a_projected_pairing_both_pages_contradict_is_left_out():
    # Salisbury at Marywood, 2026-11-07, from the Stat Lab's list: Salisbury's page said Widener, Marywood's said
    # Centenary, and both of those pages named them back.
    day, pages = date(2026, 11, 7), widener_pages()
    resolve = f.opponent_resolver(WIDENER_SCHOOLS, MEMBERS)
    assert f.contradicted({"home": "Marywood", "away": "Salisbury"}, day, pages, resolve)
    # The games the pages agree on stay, and so does a game one page lists under a name nobody resolves.
    assert not f.contradicted({"home": "Widener", "away": "Salisbury"}, day, pages, resolve)
    assert not f.contradicted({"home": "Marywood", "away": "Centenary (NJ)"}, day, pages, resolve)
    pages["Salisbury"] = [f.row(day, None, False, True, "Marywood Pacers (exact name unknown)", {}, "", "")]
    assert not f.contradicted({"home": "Marywood", "away": "Salisbury"}, day, pages, resolve)
    # A team with no row that day is not contradicted.
    assert not f.contradicted({"home": "Marywood", "away": "Hope"}, day, pages, resolve)


# ---------------------------------------------------------------- the Mac's Presto cache

PRESTO_SCHOOL = {"team": "Lasell", "type": "Presto", "schedule": "https://laserpride.lasell.edu/sports/wbkb/2025-26/schedule", "tz": "America/New_York"}


def refused(*a, **k):
    import urllib.error
    raise urllib.error.HTTPError(a[0] if a else "", 405, "Not Allowed", {}, None)


def test_schedule_rows_fall_back_to_the_macs_copy_when_presto_refuses(monkeypatch):
    day = date(2026, 11, 6)
    cache = {"pages": {"Lasell": [f.row_to_json(f.row(day, (19, 0, "America/New_York"), True, False, "Emerson", {}, "W, 70-60", ""))]}}
    monkeypatch.setattr(f, "_presto_cache", cache)
    monkeypatch.setattr(f, "get", refused)
    rows = f.schedule_rows(PRESTO_SCHOOL)
    assert [(r["day"], r["time"], r["opponent"]) for r in rows] == [(day, (19, 0, "America/New_York"), "Emerson")]
    # A Sidearm page, and a Presto school the Mac has no copy of, still raise.
    with pytest.raises(f.FETCH_ERRORS):
        f.schedule_rows({**PRESTO_SCHOOL, "team": "Emerson"})
    with pytest.raises(f.FETCH_ERRORS):
        f.schedule_rows({**PRESTO_SCHOOL, "type": "Sidearm"})
    # The Mac's own run never reads the cache.
    with pytest.raises(f.FETCH_ERRORS):
        f.schedule_rows(PRESTO_SCHOOL, fallback=False)


def test_read_presto_page_uses_the_cached_box_when_presto_refuses(monkeypatch):
    box = f.presto_box(presto_page())
    game = {"date": "2026-11-06", "home": "Lasell", "away": "Emerson", "neutral": False}
    at = f.now().isoformat(timespec="seconds")
    monkeypatch.setattr(f, "_presto_cache", {"boxes": {PRESTO_URL: {"at": at, "box": box}}})
    monkeypatch.setattr(f, "get", refused)
    assert f.read_presto_page(game, PRESTO_URL)["score"] == box["score"]
    # A score in progress counts only while the Mac's copy is fresh; a final counts at any age.
    stale = (f.now() - f.PRESTO_CACHE_LIVE - f.timedelta(minutes=1)).isoformat(timespec="seconds")
    monkeypatch.setattr(f, "_presto_cache", {"boxes": {PRESTO_URL: {"at": stale, "box": {**box, "complete": False}}}})
    with pytest.raises(f.FETCH_ERRORS):
        f.read_presto_page(game, PRESTO_URL)
    monkeypatch.setattr(f, "_presto_cache", {"boxes": {PRESTO_URL: {"at": stale, "box": box}}})
    assert f.read_presto_page(game, PRESTO_URL)["complete"] is True


def test_presto_snapshot_writes_rows_and_boxes_for_unread_games(monkeypatch, tmp_path):
    schedule = (FIX / "presto_willamette_2025.html").read_text()

    def served(url, *a, **k):
        if "/boxscores/" in url:
            return presto_page()
        if "schedule" in url:
            return schedule
        raise AssertionError(url)
    monkeypatch.setattr(f, "get", served)
    monkeypatch.setattr(f, "load_schools", lambda: {"Lasell": PRESTO_SCHOOL, "Hope": {"team": "Hope", "type": "Sidearm", "schedule": "https://x/", "tz": "America/New_York"}})
    monkeypatch.setattr(f, "SLATES", tmp_path)
    monkeypatch.setattr(f, "PRESTO_CACHE", tmp_path / "presto_cache.json")
    monkeypatch.setattr(f, "EXTRA", tmp_path / "none.json")
    monkeypatch.setattr(f, "_presto_cache", None)
    monkeypatch.setattr(f, "TODAY", "2026-11-06")
    games = [{"id": "a", "date": "2026-11-06", "home": "Lasell", "away": "Emerson", "neutral": False, "link": PRESTO_URL},
             {"id": "b", "date": "2026-11-06", "home": "Lasell", "away": "Hope", "neutral": False, "boxscore": PRESTO_URL.replace("h03q", "zzzz"), "box_read": True}]
    (tmp_path / "2026-11-06.json").write_text(json.dumps({"date": "2026-11-06", "games": games}))
    out = f.presto_snapshot()
    cache = json.loads((tmp_path / "presto_cache.json").read_text())
    assert out["errors"] == [] and set(cache["pages"]) == {"Lasell"} and list(cache["boxes"]) == [PRESTO_URL]
    assert cache["boxes"][PRESTO_URL]["box"]["complete"] is True
    assert f.row_from_json(cache["pages"]["Lasell"][0])["day"].year in (2025, 2026)
