"""The season top 10 lists build_site.py renders under the games."""
import json
import re

import build_site as b


def line(name, team, gmsc, reason="", cls=None, pts=20):
    x = {"team": team, "name": name, "reason": reason, "gmsc": gmsc,
         "line": {"min": 30, "pts": pts, "reb": 5, "ast": 2, "stl": 1, "blk": 0, "fgm": 8, "fga": 12}}
    if cls is not None:
        x["class"] = cls
    return x


def game(home, away, top, nc, home_def=1.0, away_def=1.0):
    return {"home": home, "away": away, "home_def": home_def, "away_def": away_def, "final": [70, 60],
            "top_lines": top, "newcomer_games": nc}


def write_slates(tmp_path):
    # Night one: a Hope senior's 30 against a weak defense (factor 0.8) and a Smith freshman's 24 against a strong one (1.2).
    one = {"date": "2026-11-06", "games": [game("Hope", "Smith",
            [line("Ava Jones", "Hope", 30.0), line("B. Lee", "Smith", 24.0)],
            [line("B. Lee", "Smith", 24.0, "Freshman"), line("Cara Park", "Smith", 10.0, "Transfer from Hope", cls="JR")],
            home_def=1.0, away_def=0.8)]}
    two = {"date": "2026-11-07", "games": [game("Smith", "Hope",
            [line("Ava Jones", "Hope", 26.0)] + [line(f"Player {i}", "Smith", 6.0 + i) for i in range(17)],
            [], home_def=1.2, away_def=1.0)]}
    for s in (one, two):
        (tmp_path / f"{s['date']}.json").write_text(json.dumps(s))


def test_season_lists_rank_by_adjusted_score_keep_season_n_and_fill_in_the_class(tmp_path, monkeypatch):
    write_slates(tmp_path)
    monkeypatch.setattr(b, "SLATES", tmp_path)
    monkeypatch.setattr(b, "SEASON_N", 15)  # the fixture offers 20 lines, so a list of 15 shows the cut
    rosters = b.roster_classes([("Hope", "Ava Jones", "SR"), ("Smith", "Bianca Lee", "FR"), ("Smith", "Cara Perry", "SO")])
    monkeypatch.setattr(b, "roster_classes", lambda rows=None: rosters)
    s = b.season_lines()
    # A line meets the opponent's defense. Ava's 30 at home against Smith (0.8) is 24.0. Her 26 at Smith (1.2) is 31.2.
    # The freshman's 24 at Hope (1.0) ties the 24.0. The raw score breaks that tie.
    assert [(x["name"], x["adj"], x["date"]) for x in s["top"][:3]] == [("Ava Jones", 31.2, "2026-11-07"), ("Ava Jones", 24.0, "2026-11-06"), ("Bianca Lee", 24.0, "2026-11-06")]
    # Twenty lines offered, fifteen kept: the cut falls at 11.0 and drops the five below it.
    assert len(s["top"]) == b.SEASON_N and s["top"][-1]["adj"] == 11.0
    # Class comes from a full-name roster match, then from first initial plus last name. The lookup never
    # replaces a stored class.
    assert [x["class"] for x in s["top"][:3]] == ["SR", "SR", "FR"]
    # The roster name is canonical: "B. Lee" shows as Bianca Lee. A stored class keeps its stored name.
    assert [(x["name"], x["class"]) for x in s["nc"]] == [("Bianca Lee", "FR"), ("Cara Park", "JR")]
    assert [x["name"] for x in s["fr"]] == ["Bianca Lee"]


def test_roster_player_maps_a_stored_name_to_the_roster_only_when_one_player_fits():
    rosters = b.roster_classes([("Hope", "Amy Lee", "JR"), ("Hope", "Ann Lee", "SO"), ("Hope", "Zoe Park", "FR"),
                                ("Hope", "Judith Vila", "SR"), ("Hope", "Sierra Jean", "FR")])
    assert b.roster_player("Hope", "Z. Park", rosters) == ("Zoe Park", "FR")
    assert b.roster_player("Hope", "A. Lee", rosters) == ("A. Lee", "")
    assert b.roster_player("Hope", "Amy Lee", rosters) == ("Amy Lee", "JR")
    # A box score spelling maps to the roster name: extra word, swapped order.
    assert b.roster_player("Hope", "Judith Vila Marti", rosters) == ("Judith Vila", "SR")
    assert b.roster_player("Hope", "Jean Sierra", rosters) == ("Sierra Jean", "FR")
    # A name the roster lacks stands as written.
    assert b.roster_player("Smith", "Zoe Park", rosters) == ("Zoe Park", "")


def test_season_table_matches_the_nightly_columns_and_sorts():
    x = dict(line("Ava Jones", "Hope", 30.0, cls="SR"), adj=24.0, date="2026-11-06", game={"home": "Hope", "away": "Smith"})
    html = b.nc_table([x], "none")
    assert html.count("<th ") == len(b.NC_HEADERS) and 'class="nc sortable"' in html and "aria-sort=none" in html
    assert '<td class="n">SR</td>' in html and '<span class="cls"> · SR</span>' in html and "Smith at Hope" in html and "Nov 6" in html
    assert b.nc_table([], "none") == '<p class="empty">none</p>'
    # A player with more than one line in the list shows the count beside her name. A single line shows nothing.
    assert "times" not in html
    twice = b.nc_table([x, dict(x, adj=20.0, date="2026-11-07")], "none")
    assert twice.count('<span class="times"> · 2 lines</span>') == 2
    # Keyed by team and name: a namesake on another team is a different player.
    other = b.nc_table([x, dict(x, team="Smith")], "none")
    assert "times" not in other
    # LIVE_JS draws the nightly lists with the same column list.
    js = re.search(r"const NC_HEAD='<thead><tr>'\+\[(.*?)\]\.map", b.LIVE_JS).group(1)
    assert [h.strip("'") for h in js.split(",")] == b.NC_HEADERS


def test_published_slates_carry_the_class_on_old_lines_and_the_rosters(tmp_path, monkeypatch):
    write_slates(tmp_path)
    monkeypatch.setattr(b, "SLATES", tmp_path)
    monkeypatch.setattr(b, "OUT", tmp_path / "docs" / "index.html")
    rosters = b.roster_classes([("Hope", "Ava Jones", "SR"), ("Smith", "Bianca Lee", "FR")])
    monkeypatch.setattr(b, "roster_classes", lambda rows=None: rosters)
    b.copy_slates()
    out = json.loads((tmp_path / "docs" / "slates" / "2026-11-06.json").read_text())
    g = out["games"][0]
    assert [(x["name"], x["class"]) for x in g["top_lines"]] == [("Ava Jones", "SR"), ("Bianca Lee", "FR")]
    assert [x["class"] for x in g["newcomer_games"]] == ["FR", "JR"]  # the stored JR stays
    assert g["home_classes"] == [{"name": "Ava Jones", "class": "SR"}] and g["away_classes"] == [{"name": "Bianca Lee", "class": "FR"}]
    assert b.load_slate("2026-11-06")["games"][0]["top_lines"][0]["class"] == "SR"


def test_season_results_list_each_division_iii_final_as_winner_then_loser(tmp_path, monkeypatch):
    games = [{"home": "Hope", "away": "Calvin", "final": [70, 60]}, {"home": "Alma", "away": "Hope", "final": [50, 61]},
             {"home": "Duke", "away": "Smith", "final": [90, 40], "division": 1}, {"home": "Trine", "away": "Hope", "final": None},
             {"home": "Olivet", "away": "Hope", "final": [0, 0], "off": "Postponed"}]
    (tmp_path / "2026-11-06.json").write_text(json.dumps({"date": "2026-11-06", "games": games}))
    monkeypatch.setattr(b, "SLATES", tmp_path)
    assert b.season_results() == [["Hope", "Calvin"], ["Hope", "Alma"]]


def test_ripple_games_get_a_tag_and_a_definition():
    assert "if((g.ripple||[]).length)out.push(['ripple'" in b.LIVE_JS
    assert '<dt id="ripple">Ripple games</dt>' in b.HOW
    assert "between 10% and 90%" in b.HOW
