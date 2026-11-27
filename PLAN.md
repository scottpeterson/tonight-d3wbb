# Tonight in D3 WBB: build plan

<!-- ste-allow: WBB, NPI, III, II, WP, KB, ESPN, PTS, FGM, FGA, FTA, FTM, OREB, DREB, STL, AST, BLK, PF, TO -->
<!-- ste-keep: word-choice leverage = Fixed name -->

One page with one table per night of NPI games in Division III women's basketball. Scores update live, and each game is checked at a pace set by how interesting it is.

## Scope

A game appears when both teams count for the 2026-27 NPI and the game is not an exhibition. Since 2026-10-27, a game between a counting team and a Division I or II team appears too, exhibitions included, marked D1 or D2. Those games come from the D3 team's schedule page, classified with the NCAA directory, and have no win chance, leverage, or upset term. Excluded: exhibitions, Division I and other non-D3 opponents, and second-year provisional members or earlier (Regent, Johnson & Wales Charlotte, Azusa Pacific, St. Francis (PA), Maine-Augusta). Third-year provisional members (Carlow, Penn State-Brandywine) count.

## Data flow

| Step | Where | What |
|---|---|---|
| 1. Export | Mac, `d3-bball-npi/export_scoreboard_inputs.py` | Writes `gameLeverages.json` and `newcomers.json` to `scottpeterson.github.io/data/`. `gameLeverages.json` has each remaining game's date, both teams, and each team's leverage. `newcomers.json` has each newcomer's team, name, and reason. Run after each simulation rerun and each roster update. You commit and push The D3 Stat Lab as usual |
| 2. Slate | GitHub Actions, `fetch_data.py` | Reads the two files plus `seasonSimulations.json` (tournament chance). For each game in the next two days, reads the home team's schedule page, or the away team's as a fallback. The page gives the tipoff, the home and away sides, and the live stats feed. Writes `data/slates/YYYY-MM-DD.json` |
| 3. Finals | GitHub Actions, late-night run | Reads each finished game's feed once. Stores the final score, newcomer lines, and top lines in the slate file, so past nights load without any live checks. A game can lack a complete box score in the feed 2.5 hours after tipoff, or when a schedule page posts the final. For those, it reads the Box Score link on either team's schedule page instead, for up to three days. A score a schedule page posts outranks the feed's |
| 4. Page | `build_site.py` writes `docs/index.html` and copies slates to `docs/slates/` | The browser loads the chosen night's slate and runs the live checks |

The game list comes from `gameLeverages.json`. The simulation already drops non-counting opponents and exhibitions, so the scoreboard needs no opponent-name matching. A game added to a schedule after the last simulation run is missing until the next export. The README says so.

Cron (UTC): `7 11,17,21 * * *` builds the slate (6 a.m., noon, 4 p.m. Eastern standard time). `37 7 * 11,12,1,2,3 *` records finals (2:37 a.m.).

## Interest score (0 to 100)

Inputs for each game:

- **Quality Q**: from preseason rank, `q = (1 - (rank - 1) / 409)^3` (a team with no rank counts 0.125, the midpoint). The cube makes the top steep and the middle flat. 13th against 39th is a gap of 0.17, and 213th against 239th is a gap of 0.04. On the linear scale (2026-11-07), Concordia (MN) at Wartburg, 22 at 13 with leverage 23, ranked below RIT at Rochester, 39 at 54. It was only a little less close. `Q = 0.6 * max(q1, q2) + 0.4 * min(q1, q2)`, so one elite team lifts a game more than two average teams do.
- **Leverage L**: `1 - exp(-(|lev1| + |lev2|) / 12)`. Leverage is each team's change in tournament chance between winning and losing, in percentage points. Across the 5,016 games the total has a median of 3 (L 0.22). The 90th percentile is 19.5 (L 0.80), and the top is 99.5 (L 1.00).
- **Stakes S**: `T / (T + 0.01)`, where T is the larger of the two teams' tournament chances from `seasonSimulations.json`. T of 0 gives 0, 1% gives 0.5, 5% gives 0.83, 25% gives 0.96. 131 of 411 teams are at 0%.
- **Closeness C**: `1 - |2 * WP - 1|`, where WP is the live win probability (WP) of the home team. Before tipoff, C uses the pregame WP.
- **Upset U**: the pregame underdog's gain in win probability, `U = max(0, live WP - pregame WP)` for the team that was the underdog. A 10% underdog now at 60% gives 0.5. A 45% underdog now at 55% gives 0.1. No cutoff.
- **Progress P**: share of regulation played, 0 to 1.

`interest = 100 * S * ((0.60 Q + 0.10 L) * (1 - P (1 - sqrt(C))) + (0.30 + 0.10 P) C Q + 0.25 U q_favorite)`, capped at 100.

Quality is most of the score. An even game between two top-ten teams scores about 90 before tipoff. #5 UW-Oshkosh vs #12 Wartburg at 59-41 scores 84. On 2026-11-13 it scored 49 under the earlier weights 0.30 Q, 0.25 L, 0.20 C. Leverage is small for every team in November.

Closeness counts for more late in the game. Rank and leverage fade as the result becomes certain. So a blowout between two top teams drops below a close game. Stakes multiply the whole score, so a game between two 0% teams scores near 0 and gets checked about twice a game.

## Win probability

The pregame expected margin is the preseason efficiency margin difference, converted to 70 possessions, plus 3 points for the home team. The live model treats the rest of the game as a normal draw:

- remaining expected margin `m_rem = pregame_margin * (1 - P)`
- spread `sd = 11 * sqrt(1 - P)` (points, women's D3 game-level standard deviation)
- `WP_home = Phi((lead + m_rem) / sd)`

## Polling schedule (browser)

No fixed cutoffs. Two continuous functions set the wait before a game's next light-feed check:

- **Base wait** from interest I: `60 ^ ((1 - I/100) ^ 2)` minutes. I = 100 gives 1 minute, 70 gives 1.4, 50 gives 2.8, 30 gives 7.4, 10 gives 27.6, 0 gives 60.
- **Margin stretch** from the trailing team's live chance p = min(WP, 1 - WP): multiply the wait by `(0.5 / p) ^ 0.35`. A tied game keeps the base wait. p = 0.1 multiplies it by 1.8, p = 0.01 by 3.9. Up 30 at the half (p about 0.00005) multiplies it by 25, which runs past the expected end.
- Both exponents are constants at the top of the scheduler (`WAIT_CURVE`, `MARGIN_STRETCH`) for tuning once real games run.
- The wait never runs past the expected end (tipoff plus 2 hours). When it would, the next check is the final check at the expected end, then every 15 minutes until the feed reports the game complete.

So a lopsided game moves toward one last check for the final score. A game between two 0% teams (I near 0, 60-minute wait) gets about two checks.

- Before tipoff: the first check is at tipoff plus 5 minutes.
- The feed's `IsComplete` ends all checks for that game.
- Budget: at most 40 feed requests a minute for the whole page. When more are due, the page delays the lowest-interest games first.
- Feeds are checked only while the page is visible (`visibilitychange`).
- The full feed (player box scores, about 300 KB) loads twice a game, at halftime and at the final. It loads only when the newcomer list has a player on either team. A game stopped for margin gets its second pull with the final-score check.

## Rows

The table columns are:

- interest
- game (away at home, preseason ranks)
- score
- status (clock and period, or tipoff time)
- win probability
- leverage

 Rows re-sort by interest after each check. Final games move below live games. Upcoming games sort by interest too. Tapping a row opens the feed's own live stats page.

## Top 15 newcomer games

A newcomer is a player on a 2026-27 roster who meets one of these:

- a freshman
- an incoming transfer (any division)
- absent from every 2025-26 roster's stats
- under 30 minutes in 2025-26

The section shows the 15 best newcomer game scores of the night, from every newcomer who played. It reads the full box score on every check of a live game. When a newer line arrives, it replaces that player's older line.

Game score is `PTS + 0.4 FGM - 0.7 FGA - 0.4 (FTA - FTM) + 0.7 OREB + 0.3 DREB + STL + 0.7 AST + 0.7 BLK - 0.4 PF - TO`.

The newcomer list is above the scoreboard and sorts by game score. Each row shows the player, team, reason, line, and game. The reason is freshman, transfer from X, no 2025-26 minutes, or under 30 minutes.

## Key players with no minutes

A regular is one of a team's 8 players with the most 2026-27 minutes per game (`regulars.json`). Some honorees on a 2026-27 roster are regulars too, with an `honors` list, even with no minutes:

- every 2026-27 preseason All-American
- every 2025-26 preseason or postseason All-American
- every 2025-26 All-Region pick

Honorees sort first, and all of them show. Other regulars complete the list to 35. `HONOR_SKIP` in the exporter omits honorees known to be out for the season.

The key players list holds the 35 regulars with the most minutes per game who did not play that night. Their team's box score shows them with 0 minutes or does not list them. Under each name is her count of team games in a row with no minutes. `with_streaks()` counts the earlier games from the stored slates when the slate is built. It stops at a game whose box score was never read.

The finals pass stores each game's list as `sat`. When a live game's feed has box lines at halftime, `LIVE_JS` adds that game. A side with fewer than 5 players on the floor lists no one. A played line that matches no roster player keeps regulars with its last name off the list. The rank buttons apply.

## Saved page settings

The browser keeps these settings in `localStorage`:

- each twisty's open state
- the Sort and Sort finals buttons
- My Watchlist
- the Teams rank buttons
- the team filter
- the theme
- the time zone

 The night shown and the search text are not saved.

## Feed facts

- Sidearm light feed `sidearmstats.com/<client>/wbball/game.json`: about 4 KB. It has the score, period, clock, and `IsComplete`. Holds the client's latest game, so the date must match.
- Sidearm full feed `?detail=full`: adds `Stats.<side>.PlayerGroups.Players.Values` (Name as "E. WILLIAMSON", Minutes, Fgam "made-attempted", Points, rebounds, and so on) and `Stats.<side>.Players` (FirstName, LastName, PersonId).
- Presto `data.prestolivestats.com/xml/<site>/events/<event>.xml`: StatCrew XML with `<player>` stats.
- ESPN `scoreboard/<id>` (light, about 14 KB) and `summary?event=<id>` (player box scores, about 500 KB). They are the feed for a Division I regular-season game with no Sidearm or Presto feed. Added 2026-10-28.
- StatBroadcast: no readable feed. Those rows show a link only.

## Build order

1. Exporter in `d3-bball-npi`, run once, check the two JSON files.
2. Scaffold `tonight-d3wbb` with the html-report scaffolder.
3. `fetch_data.py`: slate builder with schedule page parsing for Sidearm and Presto.
4. `build_site.py`: page, table, newcomer section, date control, Times control (viewer's zone and Eastern).
5. Page script with the feed readers and win probability. It also has the interest score, scheduler, budget, and newcomer detection.
6. Tests against a saved finished-game feed (`tests/fixtures/sidearm_nyu_full.json`).
7. Checker, phone width, both themes. Publish once the domain exists. Until then, GitHub Pages default URL.
