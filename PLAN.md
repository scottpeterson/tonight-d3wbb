# Tonight in D3 WBB: build plan

One page with one table per night of NPI games in Division III women's basketball. Scores update live, and each game is checked at a pace set by how interesting it is.

## Scope

A game appears when both teams count for the 2026-27 NPI and the game is not an exhibition. Since 2026-10-27, a game between a counting team and a Division I or II team appears too, exhibitions included, marked D1 or D2. Those games come from the D3 team's schedule page, classified with the NCAA directory, and have no win chance, leverage, or upset term. Excluded: exhibitions, Division I and other non-D3 opponents, and second-year provisional members or earlier (Regent, Johnson & Wales Charlotte, Azusa Pacific, St. Francis (PA), Maine-Augusta). Third-year provisional members (Carlow, Penn State-Brandywine) count.

## Data flow

| Step | Where | What |
|---|---|---|
| 1. Export | Mac, `d3-bball-npi/export_scoreboard_inputs.py` | Writes `gameLeverages.json` (each remaining game: date, both teams, each team's leverage) and `newcomers.json` (each newcomer: team, name, reason) to `scottpeterson.github.io/data/`. Run after each simulation rerun and each roster update. You commit and push The D3 Stat Lab as usual |
| 2. Slate | GitHub Actions, `fetch_data.py` | Reads the two files plus `seasonSimulations.json` (tournament chance). For each game in the next two days, reads the home team's schedule page (away team's as fallback) to find tipoff, the home/away side, and the live stats feed. Writes `data/slates/YYYY-MM-DD.json` |
| 3. Finals | GitHub Actions, late-night run | Reads each finished game's feed once and stores the final score and newcomer lines in the slate file, so past nights load without any live checks |
| 4. Page | `build_site.py` writes `docs/index.html` and copies slates to `docs/slates/` | The browser loads the chosen night's slate and runs the live checks |

The game list comes from `gameLeverages.json`. The simulation already drops non-counting opponents and exhibitions, so the scoreboard needs no opponent-name matching. A game added to a schedule after the last simulation run is missing until the next export. The README says so.

Cron (UTC): `7 11,17,21 * * *` builds the slate (6 a.m., noon, 4 p.m. Eastern standard time). `37 7 * 11,12,1,2,3 *` records finals (2:37 a.m.).

## Interest score (0 to 100)

Inputs for each game:

- **Quality Q**: from preseason rank, `q = 1 - (rank - 1) / 409`. `Q = 0.6 * max(q1, q2) + 0.4 * min(q1, q2)`, so one elite team lifts a game more than two average teams do.
- **Leverage L**: `1 - exp(-(|lev1| + |lev2|) / 12)`. Leverage is each team's change in tournament chance between winning and losing, in percentage points. Across the 5,016 games the total has median 3 (L 0.22), 90th percentile 19.5 (L 0.80), top 99.5 (L 1.00).
- **Stakes S**: `T / (T + 0.01)`, where T is the larger of the two teams' tournament chances from `seasonSimulations.json`. T of 0 gives 0, 1% gives 0.5, 5% gives 0.83, 25% gives 0.96. 131 of 411 teams sit at 0%.
- **Closeness C**: `1 - |2 * WP - 1|`, where WP is the live win probability of the home team. Before tipoff, C uses the pregame WP.
- **Upset U**: the pregame underdog's gain in win probability, `U = max(0, live WP - pregame WP)` for the team that was the underdog. A 10% underdog now at 60% gives 0.5. A 45% underdog now at 55% gives 0.1. No cutoff.
- **Progress P**: share of regulation played, 0 to 1.

`interest = 100 * S * ((0.30 Q + 0.25 L) * (1 - P (1 - sqrt(C))) + (0.20 + 0.15 P) C + 0.25 U)`, capped at 100. Closeness counts for more late in the game, and rank and leverage fade as the result becomes certain, so a blowout between two top teams sinks below a close game. Stakes multiply the whole score, so a game between two 0% teams scores near 0 and gets checked about twice a game.

## Win probability

The pregame expected margin is the preseason efficiency margin difference, scaled to 70 possessions, plus 3 points for the home team. The live model treats the rest of the game as a normal draw:

- remaining expected margin `m_rem = pregame_margin * (1 - P)`
- spread `sd = 11 * sqrt(1 - P)` (points, women's D3 game-level standard deviation)
- `WP_home = Phi((lead + m_rem) / sd)`

## Polling schedule (browser)

No fixed cutoffs. Two continuous functions set the wait before a game's next light-feed check:

- **Base wait** from interest I: `60 ^ ((1 - I/100) ^ 2)` minutes. I = 100 gives 1 minute, 70 gives 1.4, 50 gives 2.8, 30 gives 7.4, 10 gives 27.6, 0 gives 60.
- **Margin stretch** from the trailing team's live chance p = min(WP, 1 - WP): multiply the wait by `(0.5 / p) ^ 0.35`. A tied game keeps the base wait. p = 0.1 multiplies it by 1.8, p = 0.01 by 3.9. Up 30 at the half (p about 0.00005) multiplies it by 25, which runs past the expected end.
- Both exponents are constants at the top of the scheduler (`WAIT_CURVE`, `MARGIN_STRETCH`) for tuning once real games run.
- The wait never runs past the expected end (tipoff plus 2 hours). When it would, the next check is the final check at the expected end, then every 15 minutes until the feed reports the game complete.

So a lopsided game slides toward one last check for the final score, and a game between two 0% teams (I near 0, 60-minute wait) gets about two checks.

- Before tipoff: the first check is at tipoff plus 5 minutes.
- The feed's `IsComplete` ends all checks for that game.
- Budget: at most 40 feed requests a minute for the whole page. When more are due, the page delays the lowest-interest games first.
- Feeds are checked only while the page is visible (`visibilitychange`).
- The full feed (player box scores, about 300 KB) loads twice a game: at halftime and at the final. It loads only when the newcomer list has a player on either team. A game stopped for margin gets its second pull with the final-score check.

## Rows

Table columns: interest, game (away at home, preseason ranks), score, status (clock and period, or tipoff time), win probability, leverage. Rows re-sort by interest after each check. Final games move below live games; upcoming games sort by interest too. Tapping a row opens the feed's own live stats page.

## Newcomers having big games

A newcomer is a player on a 2026-27 roster who is a freshman, an incoming transfer (any division), absent from every 2025-26 roster's stats, or under 30 minutes in 2025-26.

A big game is any of: game score 11 or more, 20 points, 12 rebounds, 8 assists, or 5 blocks or steals. Game score = PTS + 0.4 FGM - 0.7 FGA - 0.4 (FTA - FTM) + 0.7 OREB + 0.3 DREB + STL + 0.7 AST + 0.7 BLK - 0.4 PF - TO.

The section sits above the scoreboard, lists player, team, reason (freshman, transfer from X, no 2025-26 minutes, under 30 minutes), line, and game, and sorts by game score.

## Feed facts

- Sidearm light feed `sidearmstats.com/<client>/wbball/game.json`: about 4 KB, score, period, clock, `IsComplete`. Holds the client's latest game, so the date must match.
- Sidearm full feed `?detail=full`: adds `Stats.<side>.PlayerGroups.Players.Values` (Name as "E. WILLIAMSON", Minutes, Fgam "made-attempted", Points, rebounds, and so on) and `Stats.<side>.Players` (FirstName, LastName, PersonId).
- Presto `data.prestolivestats.com/xml/<site>/events/<event>.xml`: StatCrew XML with `<player>` stats.
- StatBroadcast: no readable feed. Those rows show a link only.

## Build order

1. Exporter in `d3-bball-npi`, run once, check the two JSON files.
2. Scaffold `tonight-d3wbb` with the html-report scaffolder.
3. `fetch_data.py`: slate builder with schedule page parsing for Sidearm and Presto.
4. `build_site.py`: page, table, newcomer section, date control, Times control (viewer's zone and Eastern).
5. Page script: feed readers, win probability, interest, scheduler, budget, newcomer detection.
6. Tests against a saved finished-game feed (`tests/fixtures/sidearm_nyu_full.json`).
7. Checker, phone width, both themes. Publish once the domain exists; until then, GitHub Pages default URL.
