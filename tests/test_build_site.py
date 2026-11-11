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
            [line("Ava Jones", "Hope", 26.0)] + [line(f"Player {i}", "Smith", 12.0 + i) for i in range(12)],
            [], home_def=1.2, away_def=1.0)]}
    for s in (one, two):
        (tmp_path / f"{s['date']}.json").write_text(json.dumps(s))


def test_season_lists_rank_by_adjusted_score_keep_ten_and_fill_in_the_class(tmp_path, monkeypatch):
    write_slates(tmp_path)
    monkeypatch.setattr(b, "SLATES", tmp_path)
    rosters = b.roster_classes([("Hope", "Ava Jones", "SR"), ("Smith", "Bianca Lee", "FR"), ("Smith", "Cara Perry", "SO")])
    monkeypatch.setattr(b, "roster_classes", lambda rows=None: rosters)
    s = b.season_lines()
    # A line meets the opponent's defense: Ava's 30 at home against Smith (0.8) is 24.0, her 26 at Smith (1.2) is 31.2,
    # and the freshman's 24 at Hope (1.0) ties the 24.0, where the raw score breaks the tie.
    assert [(x["name"], x["adj"], x["date"]) for x in s["top"][:3]] == [("Ava Jones", 31.2, "2026-11-07"), ("Ava Jones", 24.0, "2026-11-06"), ("Bianca Lee", 24.0, "2026-11-06")]
    assert len(s["top"]) == b.SEASON_N and s["top"][-1]["adj"] >= 17.0
    # Class: a full-name roster match, then first initial plus last name, and a stored class wins over the lookup.
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
