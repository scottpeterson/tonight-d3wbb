"""The browser model in build_site.LIVE_JS (win chance, interest, wait, clock, newcomers), run in Node."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from build_site import LIVE_JS

FUNCS = ["logoSlug", "phi", "winProb", "quality", "stakes", "dogSurprise", "finalInterest", "interest", "waitMs", "tipMs", "nextCheck", "progressOf", "clockToSec", "periodName",
         "statusText", "gameScore", "played", "lineName", "topLines", "lineRank", "matchNewcomer", "tags", "rank", "sideTag", "winCell",
         "num", "ma", "espnState", "espnLines", "teamTokens", "overlap", "initials", "codeHit", "sideFit", "orientFit", "nameWords", "lineLast", "rosterOf", "rosterHits", "namesTeam", "feedIsGame",
         "remembered", "remember", "initState", "canBeFinal", "todayET", "siblingFeeds", "siblingLink", "modeled", "dogChance"]
CONSTS = ["GENERIC_WORDS", "TOP_N", "boxLine", "GAME_MS", "SD", "esc", "WAIT_CURVE", "norm", "GIVE_UP_MS", "SIBLING_FEEDS", "UPSET_MAX_DOG",
          "QUALITY_GATE"]

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


def test_newcomer_matching_and_played():
    roster = json.dumps([{"name": "Brooke Batchelor"}, {"name": "Ann Lee"}, {"name": "Amy Lee"}])
    assert run(f"matchNewcomer({{first:'',last:'',abbr:'B. BATCHELOR'}},{roster}).name") == "Brooke Batchelor"
    assert run(f"matchNewcomer({{first:'',last:'',abbr:'A. LEE'}},{roster})") is None
    line = "{pts:18,fgm:8,fga:14,ftm:0,fta:0,oreb:3,dreb:3,reb:6,ast:1,to:1,stl:3,blk:2,pf:2}"
    assert run(f"Math.round(gameScore({line})*10)/10") == 17.7
    corson = "{pts:18,fgm:5,fga:14,ftm:4,fta:4,oreb:2,dreb:2,reb:4,ast:0,to:2,stl:1,blk:1,pf:2,min:30}"
    assert run(f"played({corson})") is True
    assert run("played({min:0,pts:0,reb:0,ast:0,stl:0,blk:0,fga:0,fta:0,to:0,pf:0})") is False
    assert run("played({min:0,pts:0,reb:0,ast:0,stl:0,blk:0,fga:0,fta:0,to:0,pf:1})") is True


def test_top_lines_keep_the_best_fifteen_of_each_team():
    line = "{min:30,pts:%d,fgm:0,fga:0,ftm:0,fta:0,oreb:0,dreb:0,reb:0,ast:0,to:0,stl:0,blk:0,pf:0,first:'',last:'',abbr:'DOE,JANE'}"
    home = ",".join(line % p for p in range(21, 38))
    away = ",".join(line % p for p in range(1, 4))
    s = "{lines:{H:[%s],V:[%s]}}" % (home, away)
    top = run(f"topLines({{home:'NYU',away:'Brandeis'}},{s},'final')")
    # NYU's 15 best fill an unfiltered list, and Brandeis keeps its 3 for a filter that hides NYU.
    assert len(top) == 18 and top[0]["gmsc"] == 37 and top[14]["gmsc"] == 23
    assert [x["gmsc"] for x in top if x["team"] == "Brandeis"] == [3, 2, 1]
    assert top[0]["name"] == "Jane Doe" and top[0]["team"] == "NYU"


def test_line_rank_reads_the_players_team():
    g = "{home:'NYU',away:'Brandeis',home_rank:12,away_rank:250}"
    assert run(f"lineRank({{team:'NYU',game:{g}}})") == 12
    assert run(f"lineRank({{team:'Brandeis',game:{g}}})") == 250
    # A Division I opponent has no rank, so every cut leaves it out.
    assert run("lineRank({team:'Army',game:{home:'Army',away:'NYU',home_rank:null,away_rank:12}})===Infinity") is True


def test_tags_mark_upsets_close_games_and_dead_games():
    g = json.dumps(dict(GAME, pregame_wp=0.9))
    upset = run(f"tags({g},{{live:true,wp:0.45}})")
    assert "upset alert" in upset and "close" in upset
    assert "decided" in run(f"tags({json.dumps(GAME)},{{live:true,wp:0.995}})")
    assert "no tournament stakes" in run(f"tags({json.dumps(DEAD)},{{wp:0.5}})")
    assert "upset" not in run(f"tags({json.dumps(GAME)},{{final:true,wp:1}})")


D1 = dict(GAME, home="Old Dominion", away="Christopher Newport", d3="Christopher Newport", division=1, label="Exhibition",
          home_rank=None, away_rank=9, home_lev=0, away_lev=0, pregame_wp=0.5, pregame_margin=0)


def test_division_one_game_shows_a_badge_and_no_model_cells():
    g = json.dumps(D1)
    tags = run(f"tags({g},{{live:true,wp:0.2}})")
    assert "exhibition" in tags and "upset" not in tags and "not an NPI game" not in tags
    assert run(f"sideTag({g},'home')") == '<span class="dv">D1</span>'
    assert run(f"sideTag({g},'away')") == '<span class="rk top">#9</span>'
    assert run("rank(26)") == '<span class="rk">#26</span>'
    assert run(f"winCell({g},{{wp:0.3}})") == "-"
    # No upset term: a D3 team leading a D1 team does not raise interest past an even game.
    assert run(f"interest({g},{{progress:0.5,wp:0.2}})") < run(f"interest({g},{{progress:0.5,wp:0.5}})")


def test_espn_light_feed_and_summary():
    fix = Path(__file__).parent / "fixtures"
    event, summary = (fix / "espn_event.json").read_text(), (fix / "espn_summary.json").read_text()
    s = run(f"espnState({event})")
    assert (s["home"], s["away"], s["sides"]["H"]["name"], s["complete"], s["progress"], s["lines"]) == (56, 71, "Marquette", True, 1, None)
    s = run(f"espnState({summary})")
    strong = next(l for l in s["lines"]["V"] if l["last"] == "Strong")
    assert (strong["first"], strong["pts"], strong["fgm"], strong["fga"], strong["min"]) == ("Sarah", 22, 9, 20, 27)
    pre = json.loads(event)
    pre["status"]["type"]["state"] = "pre"
    pre["competitions"][0]["status"]["type"]["state"] = "pre"
    assert run(f"espnState({json.dumps(pre)})") is None


def test_espn_summary_clock_and_dead_games():
    summary = json.loads((Path(__file__).parent / "fixtures" / "espn_summary.json").read_text())
    st = summary["header"]["competitions"][0]["status"]
    st.pop("clock", None)
    st.update(period=3, displayClock="4:12", type=dict(st["type"], state="in", completed=False, name="STATUS_IN_PROGRESS"))
    s = run(f"espnState({json.dumps(summary)})")
    assert (s["status"], s["progress"]) == ("4:12 Q3", pytest.approx(0.645))
    st["type"].update(state="post", name="STATUS_POSTPONED")
    assert run(f"espnState({json.dumps(summary)})") is None


def test_checks_stop_when_a_feed_never_shows_the_game():
    g = json.dumps(dict(GAME, home_rank=350, away_rank=360, home_lev=0, away_lev=0))
    tip = "Date.parse('2026-11-14T19:00:00Z')"
    # Before the feed shows the game, the wait ends by 45 minutes after tipoff.
    assert run(f"(nextCheck({g},{{interest:0,wp:0.5}},{tip}+600000)-{tip})/60000") == 45
    assert run(f"(nextCheck({g},{{seen:true,live:true,interest:0,wp:0.5}},{tip}+600000)-{tip})/60000") > 45
    # After that, a look every 10 minutes until 4 hours past tipoff: a tournament feed shows the earlier game first.
    assert run(f"(nextCheck({g},{{noStats:true,interest:0,wp:0.5}},{tip}+3600000)-{tip})/60000") == 70
    assert run(f"nextCheck({g},{{noStats:true,interest:0,wp:0.5}},{tip}+4*3600000)") is None


def _default_night(dates, today, boot_night="2026-11-01"):
    js = (f"const BOOT={json.dumps({'dates': dates, 'night': boot_night})};function todayET(){{return '{today}'}}\n"
          + source("defaultNight") + "\nconsole.log(JSON.stringify(defaultNight()));")
    out = subprocess.run(["node", "-e", js], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_default_night_comes_from_the_device_clock_not_the_build():
    dates = ["2026-10-30", "2026-11-01", "2026-11-06", "2026-11-07"]
    assert _default_night(dates, "2026-11-01") == "2026-11-01"      # tonight has games
    assert _default_night(dates, "2026-11-02") == "2026-11-06"      # a page built Sunday, opened Monday
    assert _default_night(dates, "2027-03-01") == "2026-11-07"      # after the season: the last night
    assert _default_night([], "2026-11-02") == "2026-11-01"         # no dates at all: whatever the build chose


def test_logo_slug_matches_the_file_names():
    from tools.make_logos import slug
    for name in ("Hope", "St. John's", "Frank. & Mar.", "Trinity (CT)", "UW-La Crosse", "Mass-Boston"):
        assert run(f"logoSlug({json.dumps(name)})") == slug(name)


# Medgar Evers vs St. Joseph's Long Island, 2026-11-06: the crew typed each team's name on the other side.
SWAPPED_NAMES = {"home": 1, "away": 24, "sides": {"H": {"name": "St. Joseph's Long Island", "id": "MEDGAR"},
                                                   "V": {"name": "Medgar Evers", "id": "SJLI"}}}
MEDGAR_GAME = {"home": "Medgar Evers", "away": "St. Joseph's Long Island", "newcomers_home": [], "newcomers_away": []}


def test_team_code_beats_swapped_names():
    keep, swap = run(f"[orientFit({json.dumps(MEDGAR_GAME)},{json.dumps(SWAPPED_NAMES)},false),"
                     f"orientFit({json.dumps(MEDGAR_GAME)},{json.dumps(SWAPPED_NAMES)},true)]")
    assert keep > swap


def test_name_alone_still_flips_a_crew_home_side():
    s = {"sides": {"H": {"name": "St. Joseph's Long Island"}, "V": {"name": "Medgar Evers"}}}
    keep, swap = run(f"[orientFit({json.dumps(MEDGAR_GAME)},{json.dumps(s)},false),orientFit({json.dumps(MEDGAR_GAME)},{json.dumps(s)},true)]")
    assert swap > keep


def test_code_hits():
    assert run("[codeHit('MEDGAR','Medgar Evers'),codeHit('SJLI',\"St. Joseph's Long Island\"),codeHit('WPI','WPI'),"
               "codeHit('CALV','Calvin'),codeHit('SJLI','Medgar Evers'),codeHit('M','Medgar Evers')]") == [1, 1, 1, 1, 0, 0]


def tourney(home, away, home_roster, away_roster, home_names, away_names):
    return {"home": home, "away": away, "home_names": home_names, "away_names": away_names,
            "home_roster": home_roster, "away_roster": away_roster, "newcomers_home": [], "newcomers_away": []}


ME = [f"Ann Medg{c}" for c in "abcdef"]
SJLI = [f"Bea Long{c}" for c in "abcdef"]
FEED = {"sides": {"H": {"name": "St. Joseph's Long Island", "id": "MEDGAR"}, "V": {"name": "Medgar Evers", "id": "SJLI"}},
        "lines": {"H": [{"first": "Ann", "last": n.split()[1], "abbr": "Medg, Ann"} for n in ME],
                  "V": [{"first": "", "last": "", "abbr": n.split()[1].upper() + ",BEA"} for n in SJLI]}}


def test_feed_is_game_on_the_page():
    ours = tourney("Medgar Evers", "St. Joseph's Long Island", ME, SJLI, ["Medgar Evers"], ["St. Joseph's Long Island", "St. Joseph's (LI)"])
    other = tourney("St. Joseph's Brooklyn", "Pratt", [f"Cy Bk{c}" for c in "abcdef"], [f"Di Pr{c}" for c in "abcdef"],
                    ["St. Joseph's Brooklyn", "St. Josephs (Bklyn.)"], ["Pratt", "Pratt Institute"])
    light = {"sides": FEED["sides"], "lines": None}
    assert run(f"[feedIsGame({json.dumps(ours)},{json.dumps(FEED)}),feedIsGame({json.dumps(other)},{json.dumps(FEED)}),"
               f"feedIsGame({json.dumps(ours)},{json.dumps(light)}),feedIsGame({json.dumps(other)},{json.dumps(light)})]") == [True, False, True, False]


def test_a_team_with_no_player_on_the_feed_is_not_playing():
    aur, west, prin = [f"Ann Aur{c}" for c in "abcdef"], [f"Bea West{c}" for c in "abcdef"], [f"Cy Prin{c}" for c in "abcdef"]
    feed = {"sides": {"H": {"name": "Aurora"}, "V": {"name": "Westminster"}},
            "lines": {"H": [{"first": "Ann", "last": n.split()[1], "abbr": ""} for n in aur], "V": [{"first": "Bea", "last": n.split()[1], "abbr": ""} for n in west]}}
    real = tourney("Aurora", "Westminster (MO)", aur, west, ["Aurora"], ["Westminster (MO)", "Westminster"])
    phantom = tourney("Principia", "Aurora", prin, aur, ["Principia"], ["Aurora"])
    one_side = dict(feed, lines={"H": feed["lines"]["H"]})
    assert run(f"[feedIsGame({json.dumps(real)},{json.dumps(feed)}),feedIsGame({json.dumps(phantom)},{json.dumps(feed)}),"
               f"feedIsGame({json.dumps(phantom)},{json.dumps(one_side)})]") == [True, False, True]


STORE = ("(()=>{const m={};globalThis.KEY='t';globalThis.localStorage={getItem:k=>k in m?m[k]:null,"
         "setItem:(k,v)=>{m[k]=String(v)}};return 0})()")


def test_two_top_25_teams_with_high_leverage_outrank_a_closer_mid_table_game():
    # 2026-11-07: Concordia (MN) at Wartburg (22 at 13, leverage 23.21 and 4.43, home win chance 0.68) ranked below
    # RIT at Rochester (39 at 54, leverage 10.31 and 12.93, 0.55) while quality was linear in rank.
    wartburg = dict(GAME, home="Wartburg", away="Concordia (MN)", home_rank=13, away_rank=22, pregame_wp=0.68,
                    home_lev=4.43, away_lev=23.21, home_tourn=0.97, away_tourn=0.515)
    rochester = dict(GAME, home="Rochester", away="RIT", home_rank=54, away_rank=39, pregame_wp=0.55,
                     home_lev=12.93, away_lev=10.31, home_tourn=0.9, away_tourn=0.9)
    pregame = lambda g: run(f"interest({json.dumps(g)},{{progress:0,wp:{g['pregame_wp']}}})")
    assert pregame(wartburg) > pregame(rochester)
    # The top of the ranking is steep and the middle is flat.
    q = lambda h, a: run(f"quality({json.dumps(dict(GAME, home_rank=h, away_rank=a))})")
    assert q(13, 39) - q(39, 39) > 4 * (q(213, 239) - q(239, 239))
    assert q(None, None) == pytest.approx(0.125) and q(1, 1) == 1


def test_a_final_read_from_the_feed_survives_a_reload():
    # The feed moves on to the host's next game, and the slate has no final yet: the browser's own read holds the card.
    g = json.dumps(dict(GAME, id="2026-11-06-union-at-catholic", date="2026-11-06", tip="2026-11-06T23:00:00Z"))
    st = run(f"[{STORE},remember('2026-11-06-union-at-catholic',[93,52],'Final'),initState({g})][2]")
    assert st["final"] is True and st["score"] == [93, 52] and st["status"] == "Final"


def test_no_final_counts_before_the_game_can_have_ended():
    # UW-Stevens Point vs St. Scholastica, 2026-11-07: the slate carried a final from a 2026-10-27 build. A slate
    # final, a remembered final, and a feed read showing a complete game all wait until 45 minutes after tipoff.
    g = json.dumps(dict(GAME, id="2099-01-01-a-at-b", date="2099-01-01", tip="2099-01-01T19:00:00Z", final=[64, 53]))
    st = run(f"[{STORE},remember('2099-01-01-a-at-b',[64,53],'Final'),initState({g})][2]")
    assert st["final"] is False and st["score"] is None and st["status"] is None
    tbd = json.dumps(dict(GAME, id="2099-01-01-a-at-b", date="2099-01-01", tip=None, final=[64, 53]))
    assert run(f"initState({tbd}).final") is False
    assert run(f"canBeFinal({json.dumps(dict(GAME, tip='2020-01-01T19:00:00Z'))})") is True


def test_the_slate_final_wins_and_old_finals_drop_out():
    g = json.dumps(dict(GAME, id="2026-11-06-union-at-catholic", date="2026-11-06", tip="2026-11-06T23:00:00Z", final=[90, 50]))
    assert run(f"[{STORE},remember('2026-11-06-union-at-catholic',[93,52],'Final'),initState({g}).score][2]") == [90, 50]
    old = "remember('2020-01-01-a-at-b',[1,0],'Final'),remember('2099-01-01-c-at-d',[2,0],'Final'),Object.keys(remembered())"
    assert run(f"[{STORE},{old}][3]") == ["2099-01-01-c-at-d"]


def final_score(game, score, status="Final"):
    return run(f"interest({json.dumps(game)},{{final:true,score:{json.dumps(score)},status:{json.dumps(status)},wp:1,progress:1}})")


WJ = dict(GAME, home="Washington & Jefferson", away="Transylvania", home_rank=44, away_rank=50, pregame_wp=0.629,
          pregame_margin=3.6, home_lev=13.74, away_lev=12.05, home_tourn=0.712, away_tourn=0.78)


def test_a_close_final_between_good_teams_scores_without_an_upset():
    # Washington & Jefferson 62, Transylvania 58 on 2026-11-06 scored 0 under the live formula.
    assert 45 < final_score(WJ, [62, 58]) < 65
    assert final_score(WJ, [62, 58]) > final_score(WJ, [80, 50]) > 0


def test_an_upset_final_beats_the_same_game_won_by_the_favorite():
    assert final_score(WJ, [58, 62]) > final_score(WJ, [62, 58])
    # A big underdog that loses close beats the spread too, at a discount from winning.
    big = dict(WJ, pregame_margin=20)
    assert final_score(big, [70, 68]) > final_score(big, [90, 70]) and final_score(big, [68, 70]) > final_score(big, [70, 68])


def test_overtime_counts_as_the_closest_finish_and_dead_teams_rank_lower():
    assert final_score(WJ, [70, 62], "Final (OT)") > final_score(WJ, [70, 62])
    dead = dict(WJ, home_tourn=0, away_tourn=0)
    assert 0 < final_score(dead, [62, 58]) < final_score(WJ, [62, 58])


def test_sibling_feeds_name_the_hosts_other_courts():
    # Hope's Michele Schoon Tournament, 2026-11-07: Hope's game on wbball, Ohio Wesleyan vs UW-Platteville on wbball2.
    one = {"type": "sidearm", "url": "https://sidearmstats.com/hopecollege/wbball/game.json"}
    two = {"type": "sidearm", "url": "https://sidearmstats.com/hopecollege/wbball2/game.json"}
    assert run(f"siblingFeeds({json.dumps(one)}).map(x=>x.url)") == \
        ["https://sidearmstats.com/hopecollege/wbball2/game.json", "https://sidearmstats.com/hopecollege/wbball3/game.json"]
    assert run(f"siblingFeeds({json.dumps(two)}).map(x=>x.url)") == \
        ["https://sidearmstats.com/hopecollege/wbball/game.json", "https://sidearmstats.com/hopecollege/wbball3/game.json"]
    assert run("siblingFeeds({type:'presto',url:'https://data.prestolivestats.com/xml/a/events/b.xml'})") == []
    assert run("siblingFeeds(null)") == []
    assert run(f"siblingLink('https://athletics.hope.edu/sidearmstats/wbball/summary',{json.dumps(two)})") == \
        "https://athletics.hope.edu/sidearmstats/wbball2/summary"
    assert run(f"siblingLink('https://www.youtube.com/hopeathletics',{json.dumps(two)})") == "https://www.youtube.com/hopeathletics"
    assert run(f"siblingLink(null,{json.dumps(two)})") is None


def test_a_win_by_a_near_even_team_is_no_upset():
    # William Peace (41% at Roanoke) won 62-59 on 2026-11-07 and the card said upset. The bar is 35%.
    roanoke = json.dumps(dict(GAME, home="Roanoke", away="William Peace", pregame_wp=0.59, pregame_margin=2.5))
    assert "upset" not in run(f"tags({roanoke},{{final:true,wp:0}})")
    assert "upset" not in run(f"tags({roanoke},{{live:true,wp:0.2}})")
    dog = json.dumps(dict(GAME, pregame_wp=0.7, pregame_margin=5.8))
    assert "upset" in run(f"tags({dog},{{final:true,wp:0}})")
    assert "upset alert" in run(f"tags({dog},{{live:true,wp:0.25}})")


def test_a_game_with_no_line_gets_no_upset_tag_or_upset_interest():
    # Ohio Wesleyan (#41) vs UW-Platteville (#136), 2026-11-07, came from the schedule pages at 50% and showed upset.
    g = json.dumps(dict(GAME, pregame_wp=0.5, pregame_margin=0, modeled=False))
    assert "upset" not in run(f"tags({g},{{final:true,wp:0}})")
    assert run(f"interest({g},{{progress:0.5,wp:0.1}})") == run(f"interest({g},{{progress:0.5,wp:0.9}})")


def test_a_postponed_game_is_never_checked_and_has_no_interest():
    g = json.dumps(dict(GAME, off="Postponed"))
    assert run(f"nextCheck({g},{{interest:50,wp:0.6}},Date.parse('2026-11-14T20:00:00Z'))") is None
    assert run(f"initState({g}).interest") == 0
    assert run(f"interest({json.dumps(GAME)},{{progress:0,wp:0.6}})") > 0


def test_a_close_upset_between_mid_table_teams_scores_below_a_close_game_between_good_ones():
    # 2026-11-07: Albright (#208) over Rutgers-Camden (#86) by one scored 53, level with Immaculata at #4 Smith.
    albright = dict(GAME, home="Albright", away="Rutgers-Camden", home_rank=208, away_rank=86, home_lev=5, away_lev=5,
                    home_tourn=0.02, away_tourn=0.1, pregame_wp=0.25, pregame_margin=-7.5)
    wj = dict(GAME, home="Washington & Jefferson", away="Case Western", home_rank=44, away_rank=40, home_lev=9, away_lev=8.4,
              home_tourn=0.5, away_tourn=0.4, pregame_wp=0.55, pregame_margin=1.5)
    assert 30 < final_score(albright, [58, 57]) < 42
    assert final_score(albright, [58, 57]) < final_score(wj, [65, 59])
    # The gate leaves a top game nearly where it was.
    smith = dict(GAME, home_rank=4, away_rank=57, home_tourn=0.9, away_tourn=0.1, home_lev=3, away_lev=0.4, pregame_wp=0.9, pregame_margin=14)
    assert final_score(smith, [56, 53]) > 50
