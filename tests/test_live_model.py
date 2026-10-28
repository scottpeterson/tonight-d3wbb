"""The browser model in build_site.LIVE_JS (win chance, interest, wait, clock, newcomers), run in Node."""
import json
import re
import shutil
import subprocess

import pytest

from build_site import LIVE_JS

FUNCS = ["phi", "winProb", "interest", "waitMs", "tipMs", "nextCheck", "progressOf", "clockToSec", "periodName",
         "statusText", "gameScore", "bigGame", "matchNewcomer", "tags", "rank", "sideTag", "winCell"]
CONSTS = ["GAME_MS", "SD", "esc", "WAIT_CURVE", "norm"]

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="needs Node")


def source(name):
    """One top-level function or const statement from LIVE_JS."""
    m = re.search(r"^(?:async )?function " + name + r"\(", LIVE_JS, re.M) or re.search(r"^const (?:[A-Z_]+=[^,;]+,)*" + name + r"\b", LIVE_JS, re.M)
    assert m, name
    if LIVE_JS[m.start():].startswith("const"):
        return LIVE_JS[m.start():LIVE_JS.index("\n", m.start())]  # const statements here fit on one line
    depth, i = 0, LIVE_JS.index("{", m.start())
    while True:
        depth += {"{": 1, "}": -1}.get(LIVE_JS[i], 0)
        i += 1
        if depth == 0:
            return LIVE_JS[m.start():i]


def run(expr):
    js = "\n".join(source(n) for n in CONSTS + FUNCS) + f"\nconsole.log(JSON.stringify({expr}));"
    out = subprocess.run(["node", "-e", js], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


GAME = {"home": "Smith", "away": "Amherst", "home_rank": 4, "away_rank": 10, "home_lev": 8, "away_lev": 7,
        "home_tourn": 0.9, "away_tourn": 0.85, "pregame_wp": 0.6, "pregame_margin": 2.8, "feed": {"type": "sidearm"},
        "tip": "2026-11-14T19:00:00Z"}
DEAD = dict(GAME, home_rank=350, away_rank=360, home_lev=0, away_lev=0, home_tourn=0, away_tourn=0)


def test_win_chance_at_tipoff_uses_the_pregame_margin():
    assert run(f"winProb({json.dumps(GAME)},0,0)") == pytest.approx(0.599, abs=0.002)


def test_win_chance_up_30_at_half_is_near_certain():
    assert run(f"winProb({json.dumps(GAME)},30,0.5)") > 0.9999
    assert run(f"winProb({json.dumps(GAME)},-1,1)") == 0


def test_interest_ranks_close_elite_game_above_blowout_and_dead_game():
    g = json.dumps(GAME)
    close = run(f"interest({g},{{progress:0.85,wp:0.5}})")
    blowout = run(f"interest({g},{{progress:0.85,wp:0.999}})")
    dead = run(f"interest({json.dumps(DEAD)},{{progress:0.85,wp:0.5}})")
    assert close > 60 and blowout < close / 2 and dead == 0


def test_interest_rewards_an_upset_in_progress():
    g = json.dumps(dict(GAME, pregame_wp=0.9))
    assert run(f"interest({g},{{progress:0.6,wp:0.3}})") > run(f"interest({g},{{progress:0.6,wp:0.9}})")


def test_wait_runs_from_one_minute_to_an_hour_and_stretches_with_the_margin():
    g = json.dumps(GAME)
    assert run(f"waitMs({g},{{interest:100,wp:0.5}})/60000") == pytest.approx(1)
    assert run(f"waitMs({g},{{interest:0,wp:0.5}})/60000") == pytest.approx(60)
    assert run(f"waitMs({g},{{interest:50,wp:0.5}})/60000") == pytest.approx(60 ** 0.25)
    assert run(f"waitMs({g},{{interest:50,wp:0.1}})/waitMs({g},{{interest:50,wp:0.5}})") == pytest.approx(5 ** 0.35)


def test_next_check_waits_for_tipoff_then_caps_at_the_expected_end():
    g = json.dumps(GAME)
    tip = "Date.parse('2026-11-14T19:00:00Z')"
    assert run(f"(nextCheck({g},{{interest:50,wp:0.5}},{tip}-3600000)-{tip})/60000") == 5
    assert run(f"(nextCheck({g},{{live:true,interest:0,wp:0.0001}},{tip}+6600000)-{tip})/60000") == 120
    assert run(f"(nextCheck({g},{{live:true,interest:0,wp:0.5}},{tip}+7800000)-{tip})/60000") == 145
    assert run(f"nextCheck({g},{{final:true}},{tip})") is None


def test_clock_and_status():
    assert run("progressOf(3,300,4)") == pytest.approx(0.625)
    assert run("progressOf(5,120,4)") == 1
    assert run("clockToSec('04:12')") == 252
    assert run("[statusText(2,0,4),statusText(3,0,4),statusText(4,65,4),statusText(5,10,4)]") == \
        ["Halftime", "End Q3", "1:05 Q4", "0:10 OT"]


def test_newcomer_matching_and_big_game():
    roster = json.dumps([{"name": "Brooke Batchelor"}, {"name": "Ann Lee"}, {"name": "Amy Lee"}])
    assert run(f"matchNewcomer({{first:'',last:'',abbr:'B. BATCHELOR'}},{roster}).name") == "Brooke Batchelor"
    assert run(f"matchNewcomer({{first:'',last:'',abbr:'A. LEE'}},{roster})") is None
    line = "{pts:18,fgm:8,fga:14,ftm:0,fta:0,oreb:3,dreb:3,reb:6,ast:1,to:1,stl:3,blk:2,pf:2}"
    assert run(f"Math.round(gameScore({line})*10)/10") == 17.7
    assert run(f"bigGame({line})") is True
    corson = "{pts:18,fgm:5,fga:14,ftm:4,fta:4,oreb:2,dreb:2,reb:4,ast:0,to:2,stl:1,blk:1,pf:2}"
    assert run(f"bigGame({corson})") is True
    assert run(f"bigGame(Object.assign({corson},{{to:3}}))") is False


def test_tags_mark_upsets_close_games_and_dead_games():
    g = json.dumps(dict(GAME, pregame_wp=0.9))
    upset = run(f"tags({g},{{live:true,wp:0.45}})")
    assert "upset alert" in upset and "close" in upset and "top 25" in upset and "high leverage" in upset
    assert "decided" in run(f"tags({json.dumps(GAME)},{{live:true,wp:0.995}})")
    assert "no tournament stakes" in run(f"tags({json.dumps(DEAD)},{{wp:0.5}})")
    assert "upset" not in run(f"tags({json.dumps(GAME)},{{final:true,wp:1}})")


D1 = dict(GAME, home="Old Dominion", away="Christopher Newport", d3="Christopher Newport", division=1, label="Exhibition",
          home_rank=None, away_rank=9, home_lev=0, away_lev=0, pregame_wp=0.5, pregame_margin=0)


def test_division_one_game_shows_a_badge_and_no_model_cells():
    g = json.dumps(D1)
    tags = run(f"tags({g},{{live:true,wp:0.2}})")
    assert "Division I opponent, not an NPI game" in tags and "exhibition" in tags and "upset" not in tags
    assert run(f"sideTag({g},'home')") == '<span class="dv">D1</span>'
    assert run(f"sideTag({g},'away')") == '<span class="rk">#9</span>'
    assert run(f"winCell({g},{{wp:0.3}})") == "-"
    # No upset term: a D3 team leading a D1 team does not raise interest past an even game.
    assert run(f"interest({g},{{progress:0.5,wp:0.2}})") < run(f"interest({g},{{progress:0.5,wp:0.5}})")
