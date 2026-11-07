# Tonight in D3 WBB

Live scores for every Division III women's basketball game that counts for the NPI, sorted by how interesting each game is right now. `PLAN.md` holds the design: the interest score, the win probability model, the check schedule, and the newcomer rules.

## Files

| File | Purpose |
|------|---------|
| `site.json` | Name, domain, analytics code, time zones, accent colors |
| `fetch_data.py` | Builds `data/slates/YYYY-MM-DD.json` for today and tomorrow, records finals, newcomer lines, and top lines for the last three days (from the live feed, then from the Box Score link on either team's schedule page once the game is 2.5 hours past tipoff; a stored final is dropped while the game cannot have ended yet, before 45 minutes after tipoff, so a wrong score cannot ride along from build to build), and writes `data/data.json` (fetch time, errors, game count per date). A D3 game a schedule page lists before the Stat Lab's `gameLeverages.json` does (a tournament's second-day game, TBA on the pages until the first day ends) joins the slate with an even win chance and no leverage until the next NPI update. Games against Division I and II teams do not appear |
| `build_site.py` | Renders `docs/index.html`, embeds the default night's slate, and copies the slates to `docs/slates/`. `LIVE_JS` holds the browser model and scheduler |
| `data/schools.csv` | Each school's schedule page, page type (Sidearm or Presto), and time zone. Written by `tools/make_schools.py` |
| `data/ncaa_members.csv` | Every NCAA school with women's basketball: name, division, conference, athletics site. Written by `tools/make_ncaa_members.py` |
| `tools/make_ncaa_members.py` | Rebuilds `data/ncaa_members.csv` from the NCAA directory |
| `data/extra_games.json` | Games the schedule pages miss, such as a D3 exhibition at a Division I school on a page the reader cannot parse. The file's `note` lists the fields |
| `data/team_names.csv`, `data/rosters.csv` | Every name a source uses for each D3 team, and each team's 2026-27 roster. A live stats feed counts for a game only when it shows that game: two of our teams' players in its box score make it ours, none make it another game's (a host's crew can run one feed for its whole tournament), and without players one feed side has to match a team name or code. Written by `tools/make_team_data.py`; rerun it after a roster update |
| `tools/make_team_data.py` | Rebuilds `data/team_names.csv` from `D3 Schools Name Mapping.csv` and `data/rosters.csv` from `2027/players.csv` in `~/projects/d3-bball-npi` |
| `tools/make_schools.py` | Rebuilds `data/schools.csv` from `~/projects/d3-bball-npi` (`team_base_websites.csv`, `school_demographics.csv`) |
| `tools/dispatch_finals.sh`, `tools/com.scottpeterson.tonight-d3wbb-finals.plist` | Start the site's runs by dispatch from the Mac, because GitHub's cron starts hours late or not at all (the 6 a.m. Eastern run started at 9:17 a.m. on 2026-11-07): a full run once in each daily hour (6 a.m., noon, 4 p.m. Eastern standard time, plus 2 a.m. in season) and a finals pass every 20 minutes on game nights. Install with `cp tools/com.scottpeterson.tonight-d3wbb-finals.plist ~/Library/LaunchAgents/ && launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.scottpeterson.tonight-d3wbb-finals.plist`. Log in `logs/dispatch.log` |
| `tools/make_logos.py` | Writes `docs/logos/<slug>.webp` from `logo_thumbs.json` in `~/projects/d3-bball-npi`. GitHub Actions cannot read that repo, so the logos are committed. Rerun it when a school changes its logo or a team joins. A team with no file, such as a D1 or D2 opponent, shows its first letter |
| `requirements.txt` | BeautifulSoup, for the Presto schedule templates |
| `tests/` | Parser tests against saved pages and feeds in `tests/fixtures/`, and browser model tests that run `LIVE_JS` functions in Node |
| `docs/` | The published page and slates. With a custom domain, `docs/CNAME` holds it |
| `.github/workflows/update.yml` | Scheduled fetch, build, commit |

## Build

```bash
pip install -r requirements.txt
python3 fetch_data.py
python3 build_site.py
python3 ~/.claude/skills/html-report/scripts/check_page.py docs/index.html
python3 -m http.server 8000 --directory docs   # the page fetches other nights' slates, so open it over HTTP
```

Two environment variables help with testing:

- `TONIGHT_STATLAB_DIR=../scottpeterson.github.io/data` reads The D3 Stat Lab files from the local checkout instead of thed3statlab.com.
- `TONIGHT_TODAY=2026-11-07` builds slates as if that date were today.

Edit the generator, never `docs/index.html`.

## Tests

```bash
pip install pytest
python3 -m pytest tests -q
```

The browser model tests need `node` on the path and skip without it.

## Data sources

| Source | What it gives | Quirks |
|---|---|---|
| `thed3statlab.com/data/gameLeverages.json` | Every scheduled game between two NPI teams: date, home, away, neutral, preseason efficiency ranks, pregame margin and home win chance, each team's leverage | Written by `export_scoreboard_inputs.py` in `d3-bball-npi` from `games.txt`, `game_leverages.csv`, and `preseason_efficiency.csv`. Raw efficiency margins stay out. A game added to a schedule after the last export is missing until the next one |
| `thed3statlab.com/data/newcomers.json` | Freshmen, incoming transfers, players with no 2025-26 minutes, and players under 30 minutes in 2025-26 | Same exporter, from `players.csv` for 2027 and 2026 |
| `thed3statlab.com/data/seasonSimulations.json` | Each team's tournament chance (`Tourn%`) | Published with the simulations |
| Sidearm schedule pages | Tipoff, home or away, live stats link | Times often print with no zone, so each school's zone comes from `data/schools.csv`. The home page sometimes lists a game with no time while the away page has it. Conference-hosted pages (Penn St. Brandywine on gounitedeast.com) use the older table layout with no live stats links; `sidearm_table_rows()` reads them. Many Division I sites use a newer layout of game cards ("vs" or "at" stamp, "Oct 28 (Wed) 7:00 PM", opponent linked as "<name> Website", Live stats or Stats link); `sidearm_card_rows()` reads them. A D1 or D2 host's page fills a tipoff or link the D3 page leaves out; its times print without a zone, so the D3 team's zone stands in. Hosts label exhibitions differently from their guests (Green Bay: "UW-Stevens Point (Exh.)"), so D1 and D2 games match rows whatever the label. Some hosts do not list an exhibition at all (Cal State Fullerton, Binghamton) |
| Presto schedule pages (47 schools) | Same | At least three templates (cards, newer cards, tables). Every template puts "Women's Basketball event: November 14 02:00 PM: ..." in each link's `aria-label`. Source URLs name the 2025-26 season; `season_url()` swaps in 2026-27. Some sites sometimes return a 200 page with no games; the fetcher reads it a second time. On 2026-10-26, 45 of the 47 Presto sites answered scripted requests with an AWS WAF bot challenge (Austin returned 403, VTSU Johnson 404), so their games took tipoff and feed from the opponent's page. On 2026-10-28, 23 Presto sites answered 405 (CloudFront "Request blocked"). Their NPI games still come from the opponent's page; their D1 and D2 games come from the Sidearm hub (same day) and ESPN (regular season). Huntingdon uses a template the reader does not parse |
| NCAA directory `web3.ncaa.org/directory/api/directory/memberList?type=12&sportCode=WBB` | Each NCAA school with women's basketball: division, conference, athletics site | Open JSON, about 1.3 MB. Sidearm schedule rows link the opponent's athletics site, which matches the directory's `athleticWebUrl`; Presto rows have no such link, so those match by name and only when one school fits. NAIA and two-year schools are not in it |
| Sidearm feed `sidearmstats.com/<client>/wbball/game.json` | Score, period, clock, `IsComplete` (about 4 KB) | CORS open. Holds the client's latest game, so the page checks `Game.Date`; a crew that reuses the feed for its next game takes the earlier box score with it, which is why finals fall back to the schedule page's Box Score link (`/sports/womens-basketball/stats/<season>/<opponent>/boxscore/<id>`: visiting team first, names as "Last,First", date in the title). Player box scores only with `?detail=full` (about 300 KB). Every Sidearm site has a stats page that names a client. A client's feed answers 404 until its first game of the season starts, and a school whose crews use StatBroadcast may never have one, so a 404 before tipoff tells you nothing. `house_feed()` uses the host's feed without reading it first. A tournament host runs its own game on `wbball` and the other game on `wbball2` (Hope, 2026-11-07), and the schools' pages can link either folder until the hour before tipoff, so when a feed shows another game after tipoff, the page and the finals pass try the host's other folders (`sibling_feeds()`, `siblingFeeds()`) and adopt the one that shows the game. Newer sites also serve one game at `<site>/api/livestats?game_id=<n>`, with CORS on some sites and not others; the page does not use it |
| Presto feed `data.prestolivestats.com/xml/<site>/events/<event>.xml` | StatCrew XML with player stats | Only when the live stats link points at prestolivestats.com. The school-hosted `boxscores/*.xml` links are HTML pages without CORS |
| Presto box score page `<site>/sports/wbkb/<season>/boxscores/<YYYYMMDD>_<id>.xml` | Linescore (period or Final, visitor row first), then a player table per team | Serves HTML despite the `.xml` name, with no CORS, so only the fetcher reads it. It updates during the game. The date line can run a day ahead (UTC), so the date comes from the link. Player cells come as `F 5 Marissa Nudd` or `25 - Long,Caroline - F`; most mark the name with `.player-name`. Some sites answer 403 or 405 to the runner (Wentworth), and a link can 404 (Fitchburg St., 2026-11-06); the opponent's page link is the fallback |
| Sidearm hub feed `aggregation-service.sidearmsports.com/services/games.ashx?start_date=…&end_date=…` (behind sidearmstats.com/hub) | Every game a Sidearm school lists: tipoff in UTC, both teams' names and sites, division, the live stats link | Open JSON, CORS open. Answers only for about yesterday through tomorrow. Team sites do not always match ours (SUNY Geneseo: knights.geneseo.edu; Binghamton: binghamtonbearcats.com, bubearcats.com in the NCAA directory), so `hub_teams()` falls back to the live stats link's site (it belongs to the school that posted the listing: `location.han` "A" means the away team) and then the name. Games added from the hub use sites only. D3 pages often leave out an exhibition at a Division I school (Spalding at Bellarmine, 2026-10-29), so the hub can add a game for any D3 team. A listing can carry the wrong opponent record: on 2026-10-28 Indiana listed "Marian" with Marian of Wisconsin's site and school ID, while Marian of Indiana (NAIA) listed the same game. A team that the hub puts against two different `school_global_id` values that day adds no game. Exhibition marks sit in `game_promotion_name` ("Exhibition", "Scrimmage") or on a team name. Status "C" listings are skipped. A TBA game carries midnight UTC on its date A stat crew can leave a template's team name in the feed (Butler's feed named Columbia as the visitor for the Franklin game; the visitor ID was `FRA`) |
| ESPN `site.api.espn.com/apis/site/v2/sports/basketball/womens-college-basketball` | `scoreboard?dates=YYYYMMDD&groups=50&limit=500`: Division I regular-season games, including against D3 teams. `scoreboard/<id>` (about 14 KB) for live score; `summary?event=<id>` (about 500 KB) for player box scores | CORS open. No exhibitions. A team outside Division I has `conferenceId` null and `isActive` false. Names are ESPN's ("Rose Hulman", "Colby Sawyer"), so matches need an exact name; ESPN adds a game only for a D3 team whose page could not be read, and only when the host's schedule page links that D3 team's site that day. It gives a feed to a D1 game with no other feed (hosts that use StatBroadcast) |
| StatBroadcast | Nothing readable | Cloudflare blocks scripted requests, the data calls need per-session tokens, and there is no CORS. Rows show the link only |

## Refresh chores

- After each simulation rerun or roster update, run `uv run python export_scoreboard_inputs.py` in `~/projects/d3-bball-npi`, then commit and push The D3 Stat Lab.
- When a school changes its site or a team joins, update `team_base_websites.csv` in `d3-bball-npi`, then run `python3 tools/make_schools.py` here.
- Each fall, run `python3 tools/make_ncaa_members.py`, because schools change divisions.
- When a known D1 or D2 game is missing (no page lists it, it is an exhibition on a blocked team's schedule, or the hub has not picked it up yet), add it to `data/extra_games.json` with `division`, `d3`, and `tip`.
- `make_schools.py` keeps only the teams in `2027/teams_mapping.txt`. Change `SEASON` there each fall.

## Refresh

GitHub Actions runs `fetch_data.py` and `build_site.py` at 6 a.m., noon, and 4 p.m. Eastern standard time (`7 11,17,21 * * *`), and at 2:37 a.m. from November to March to record finals (`37 7 * 11,12,1,2,3 *`). On game nights from November to March it also runs `fetch_data.py --finals` every 20 minutes from 6 p.m. to 1 a.m. Eastern standard time: finals, box score lines, and live score snapshots from Presto box score pages, reading only the schedule pages those games need (about 80 seconds). The pass also takes a live stats link a schedule page added or changed since the last full run (`refresh_feed()`): schools post the link on game day, and a new link counts when the game had no feed or sits on the same site as the old one. GitHub started the 4 p.m. run 3 hours 44 minutes late on 2026-11-06, never started the 20-minute runs, and started the 6 a.m. run at 9:17 a.m. on 2026-11-07, so the Mac starts every run by dispatch (`tools/dispatch_finals.sh` through launchd, every 20 minutes). The cron stays as a backup for when the Mac sleeps. When two runs write at once, the later run's generated files win the rebase. An open page rereads tonight's slate every 10 minutes to pick these up. A card whose feed has not shown its game 45 minutes after tipoff keeps looking every 10 minutes until 4 hours after tipoff, because a tournament host's feed shows the earlier game first. Live scores do not come from the cron: the page reads each game's feed in the viewer's browser. A final the browser reads from a feed stays in that browser for 4 days, so a reload keeps the game final after the feed moves on to the host's next game.
