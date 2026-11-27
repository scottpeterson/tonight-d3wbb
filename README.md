# Tonight in D3 WBB

<!-- ste-allow: WBB, NPI, III, II, TBA, KB, MB, AWS, VTSU, ESPN, CORS, WAF, UTC, NC, SUNY -->
<!-- ste-keep: word-choice leverage = Fixed name -->
<!-- ste-keep: synonym-rotation directory folder = Two concepts -->
<!-- ste-keep: synonym-rotation start launch = Two concepts -->

Live scores for every Division III women's basketball game that counts for the NPI, sorted by how interesting each game is right now. `PLAN.md` holds the design: the interest score, the win probability model, the check schedule, and the newcomer rules.

## Files

| File | Purpose |
|------|---------|
| `site.json` | Name, domain, analytics code, time zones, accent colors |
| `fetch_data.py` | Builds `data/slates/YYYY-MM-DD.json` for today and tomorrow and writes `data/data.json`. The rules are under [Slates](#slates) |
| `player_names.py` | Maps a box line to its roster player for the fetcher, the builder, and the page (as `matchNewcomer()`). The rules are under [Player names](#player-names) |
| `build_site.py` season lists | Three lists under the games, from `season_lines()`. The rules are under [Season lists](#season-lists) |
| `build_site.py` | Renders `docs/index.html`, embeds the default night's slate, and copies the slates to `docs/slates/`. `LIVE_JS` holds the browser model and scheduler |
| `data/schools.csv` | Each school's schedule page, page type (Sidearm or Presto), and time zone. Written by `tools/make_schools.py` |
| `data/ncaa_members.csv` | Every NCAA school with women's basketball. Each row has the name, division, conference, and athletics site. Written by `tools/make_ncaa_members.py` |
| `tools/make_ncaa_members.py` | Rebuilds `data/ncaa_members.csv` from the NCAA directory |
| `data/extra_games.json` | Games the schedule pages miss, such as a D3 exhibition at a Division I school on a page the reader cannot parse. The file's `note` lists the fields |
| `data/team_names.csv`, `data/rosters.csv` | Every name a source uses for each D3 team, and each team's 2026-27 roster. The feed rules that use them are under [Live stats feeds](#live-stats-feeds). Written by `tools/make_team_data.py`. Rerun it after a roster update |
| `data/other_d3_names.csv` | The names of Division III teams that play this season but do not count (Johnson & Wales Charlotte, Regent, St. Francis, Azusa Pacific). A schedule row whose name also fits one of them, such as a bare "Johnson & Wales University", names no opponent. Written by `tools/make_team_data.py` |
| `tools/make_team_data.py` | Rebuilds `data/team_names.csv` and `data/other_d3_names.csv` from `D3 Schools Name Mapping.csv` and `data/rosters.csv` from `2027/players.csv` in `~/projects/d3-bball-npi` |
| `tools/make_schools.py` | Rebuilds `data/schools.csv` from `~/projects/d3-bball-npi` (`team_base_websites.csv`, `school_demographics.csv`) |
| `tools/dispatch_finals.sh`, `tools/com.scottpeterson.tonight-d3wbb-finals.plist` | Start the site's runs by dispatch from the Mac. The schedule is under [Refresh](#refresh). Install with `cp tools/com.scottpeterson.tonight-d3wbb-finals.plist ~/Library/LaunchAgents/ && launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.scottpeterson.tonight-d3wbb-finals.plist`. Log in `logs/dispatch.log` |
| `tools/make_logos.py` | Writes `docs/logos/<slug>.webp` from `logo_thumbs.json` in `~/projects/d3-bball-npi`. GitHub Actions cannot read that repo, so the logos are committed. Rerun it when a school changes its logo or a team joins. A team with no file, such as a D1 or D2 opponent, shows its first letter |
| `data/presto_cache.json` | The Mac's copy of Presto data, written by `fetch_data.py --presto` from the runner clone. It holds every Presto school's schedule rows and the Presto box score pages of games still without a final. It also holds where each Presto short link (`<site>/links/<id>`) redirects. The GitHub runner reads it when a Presto page answers 405. The runner always reads the short links through it |
| `tools/probe.py`, `.github/workflows/probe.yml` | Print what a GitHub runner gets from a URL with the site's user agent and a browser's: `gh workflow run probe.yml -f urls="URL URL"` |
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

## Slates

- `fetch_data.py` builds `data/slates/YYYY-MM-DD.json` for today and tomorrow. Each slate records finals, newcomer lines, and top lines for the last three days.
- The lines come from the live feed first. They switch to the Box Score link on either team's schedule page at one of two points. One is 2.5 hours after tipoff. The other is when a schedule page posts its final score.
- A game cannot end before 45 minutes after tipoff. The fetcher drops a stored final in that window, so a wrong score cannot stay from build to build.
- `data/data.json` holds the fetch time, the errors, the game count per date, and each team's conference for the team filter.
- On each run, `restamp_defense()` gives every stored slate the day's defense factors from `gameLeverages.json`. The season lists then rank every line by the current ratings.
- A schedule page can list a D3 game before the Stat Lab's `gameLeverages.json` does. An example is a tournament's second-day game, which the pages show as TBA until the first day ends. That game joins the slate with an even win chance, no leverage, and `modeled: false`. The page never calls its result an upset.
- A Stat Lab game that both schedule pages contradict stays out. Each page lists another D3 opponent that day. That opponent's page names it back. Such a game is a projected tournament pairing (Salisbury at Marywood, 2026-11-07). The run prints it as a note.
- A Stat Lab game that neither page lists on its day moves to the day the pages agree on, within three days. If the pair is already on that day, the fetcher drops the game. La Verne vs Pacific was listed on 2026-11-07 and 11-08 and played on the 8th.
- A Stat Lab game that neither page lists at all stays out when both pages were read and neither shows a game that day. Buena Vista at North Central (MN) on 2026-11-10 is an example. Massey listed it, and both pages showed only Nov 7 and Nov 14.
- A game that a page adds stays out when either page calls it a scrimmage (Merchant Marine at Lehman, 2026-11-07).
- The fetcher resolves a page opponent by its link's site first, then by a name that fits one D3 school.
- The fetcher trusts a link to another NCAA member's site over the name. On 2026-11-15, NC Wesleyan's "Johnson & Wales (N.C.)" linked charlotte.jwuathletics.com. By name alone, the fetcher would have read it as Johnson & Wales Providence.
- A name that also fits a Division III team that does not count names no opponent (Hollins's "Johnson & Wales University", 2026-11-21).
- Games against Division I and II teams do not appear.

## Player names

- The roster name is canonical. `player_names.py` maps a box score spelling that differs to it in these cases, each only when one player fits:
  - the same words in another order
  - one name's words inside the other's
  - first initial plus last name
- A name that the roster lacks stays as written until the roster lists it.
- `newcomer_of()` and `newcomerOf()` match a newcomer line against the whole roster first. So a teammate who is not a newcomer stays a candidate. On 2026-11-14, Jaydn Pingree scored 34 points for Maine Farmington. A match against the newcomer list alone gave the points to her sister Jazmine, the only newcomer named Pingree.

## Season lists

- `season_lines()` builds three lists under the games. Each list shows the 20 best adjusted game scores since opening night. One list covers any player, one covers newcomers, and one covers freshmen.
- The lists read only the lines each slate stores, at most 15 per team per game. They keep a running cut at the fifteenth score.
- A player with more than one line in a list shows the count beside her name (`line_row()`, keyed by team and name).
- Every line table shows the class year from `data/rosters.csv`. `tools/make_team_data.py` writes that file from `players.csv`. A line stored before the slates had a class gets it by name at build time.

## Data sources

| Source | What it gives |
|---|---|
| `thed3statlab.com/data/gameLeverages.json` | Every scheduled game between two NPI teams, with date, home, away, neutral, season efficiency ranks, pregame margin, home win chance, and each team's leverage. It also has `defense`, each team's factor for opposing players' game scores |
| `thed3statlab.com/data/newcomers.json` | Freshmen, incoming transfers, players with no 2025-26 minutes, and players under 30 minutes in 2025-26 |
| `thed3statlab.com/data/regulars.json` | Each team's 8 players with the most 2026-27 minutes per game, plus its All-American and All-Region honorees with an `honors` list. Each player has points, rebounds, and assists per game |
| `thed3statlab.com/data/seasonSimulations.json` | Each team's tournament chance (`Tourn%`) and conference (`Conf`, for the team filter) |
| Sidearm schedule pages | Tipoff, home or away, live stats link |
| Presto schedule pages (47 schools) | Tipoff, home or away, live stats link |
| NCAA directory `web3.ncaa.org/directory/api/directory/memberList?type=12&sportCode=WBB` | Each NCAA school with women's basketball, with its division, conference, and athletics site |
| Sidearm feed `sidearmstats.com/<client>/wbball/game.json` | Score, period, clock, and `IsComplete` (about 4 KB) |
| Presto feed `data.prestolivestats.com/xml/<site>/events/<event>.xml` | StatCrew XML with player stats |
| Presto box score page `<site>/sports/wbkb/<season>/boxscores/<YYYYMMDD>_<id>.xml` | Linescore (period or Final, visitor row first), then a player table per team |
| Sidearm hub feed `aggregation-service.sidearmsports.com/services/games.ashx?start_date=…&end_date=…` (behind sidearmstats.com/hub) | Every game a Sidearm school lists. Each listing has the tipoff in UTC, both teams' names and sites, the division, and the live stats link |
| ESPN `site.api.espn.com/apis/site/v2/sports/basketball/womens-college-basketball` | `scoreboard?dates=YYYYMMDD&groups=50&limit=500` gives Division I regular-season games, including games against D3 teams. `scoreboard/<id>` (about 14 KB) gives the live score. `summary?event=<id>` (about 500 KB) gives player box scores |
| StatBroadcast | Nothing readable |

### The D3 Stat Lab files

- `export_scoreboard_inputs.py` in `d3-bball-npi` writes all four files.
- `gameLeverages.json` comes from `games.txt`, `game_leverages.csv`, and `eff.txt`. `eff.txt` blends the preseason projection into the box-score rating over each team's first eight games. Raw efficiency margins stay out.
- The `defense` factor is the cube of the D3 average adjusted defense divided by the team's. `DEFENSE_EXPONENT` in `export_scoreboard_inputs.py` sets the power, from a fit of this season's lines.
- A game added to a schedule after the last export is missing until the next export.
- `newcomers.json` comes from `players.csv` for 2027 and 2026. `regulars.json` comes from `players.csv` for 2027.
- The finals pass and the page list the regulars with no minutes in a game (`sat_out()`, `satOut()`). Team games are the team's total minutes divided by 200. A missing `regulars.json` leaves the list empty.
- `seasonSimulations.json` is published with the simulations.

### Sidearm schedule pages

- Times often print with no zone, so each school's zone comes from `data/schools.csv`.
- The home page sometimes lists a game with no time while the away page has it.
- Conference-hosted pages (Penn St. Brandywine on gounitedeast.com) use the older table layout with no live stats links. `sidearm_table_rows()` reads them.
- Many Division I sites use a newer layout of game cards. A card has a "vs" or "at" stamp, a date such as "Oct 28 (Wed) 7:00 PM", the opponent linked as "<name> Website", and a Live stats or Stats link. `sidearm_card_rows()` reads them.
- A D1 or D2 host's page supplies a tipoff or link that the D3 page omits. Its times print without a zone, so the D3 team's zone applies.
- Hosts label exhibitions differently from their guests (Green Bay: "UW-Stevens Point (Exh.)"). So D1 and D2 games match rows whatever the label. Some hosts do not list an exhibition at all (Cal State Fullerton, Binghamton).
- Rhodes (rhodeslynx.com, 2026-11-14) uses a component layout. It embeds the season's first 20 games as JSON in `var obj = {"type":"events", ...}` script blocks. The browser draws the list, so the list reader finds nothing. `sidearm_component_rows()` reads the JSON (links, results, tipoffs). It fills the rest of the season from the site's plain-text schedule, `/services/schedule_txt.ashx?schedule=<id>`. That schedule has no links and shows "Postponed" in the result column.
- A Sidearm row's result column reads "Postponed" or "Canceled" when the game is off. Such a game shows that word in place of its tipoff, gets no checks, and keeps no final.
- The regex must stop at the class name. The row also has a `sidearm-schedule-game-result-final` element that says "Final" (Hendrix vs Rhodes, 2026-11-07).

### Presto schedule pages

- Presto sites use at least three templates. They are cards, newer cards, and tables. Every template puts "Women's Basketball event: November 14 02:00 PM: ..." in each link's `aria-label`.
- Source URLs name the 2025-26 season. `season_url()` swaps in 2026-27.
- Some sites sometimes return a 200 page with no games. The fetcher then reads the page a second time.
- On 2026-10-26, 45 of the 47 Presto sites answered scripted requests with an AWS WAF bot challenge. Austin returned 403 and VTSU Johnson returned 404. Their games took tipoff and feed from the opponent's page.
- On 2026-10-28, 23 Presto sites answered 405 (CloudFront "Request blocked").
- On 2026-11-07, every Presto schedule and box score page answered 405 to the runner with any user agent, and answered the Mac. Finals for Presto-only matchups (La Roche at Carnegie Mellon, Thomas at Elms) never arrived.
- The Mac now reads those pages into `data/presto_cache.json` before each dispatched run (`fetch_data.py --presto`). When a Presto page refuses the runner, `schedule_rows()` and `read_presto_page()` use that copy. A cached in-progress box score counts as a snapshot for 2 hours. A cached final counts at any age.
- Their D1 and D2 games come from the Sidearm hub (same day) and ESPN (regular season).
- Huntingdon uses a template the reader does not parse.

### NCAA directory

- The directory is open JSON, about 1.3 MB.
- Sidearm schedule rows link the opponent's athletics site, which matches the directory's `athleticWebUrl`. Presto rows have no such link, so those rows match by name, and only when one school fits.
- National Association of Intercollegiate Athletics (NAIA) and two-year schools are not in it.

### Live stats feeds

A live stats feed counts for a game only when it shows that game:

- Two of our teams' players in its box score make the feed ours.
- If none of our players appear, the feed belongs to another game. A host's crew can run one feed for its whole tournament.
- Without players, one feed side has to match a team name or code.

Sidearm feeds:

- CORS is open. The feed holds the client's latest game, so the page checks `Game.Date`.
- A crew can reuse the feed for its next game. The earlier box score is then gone from the feed. So the fetcher reads finals from the schedule page's Box Score link (`/sports/womens-basketball/stats/<season>/<opponent>/boxscore/<id>`). That page lists the visiting team first, writes names as "Last,First", and has the date in the title.
- Player box scores come only with `?detail=full` (about 300 KB).
- A crew's box score page can name one team's players after the other team's. Rhodes's page for Babson at Dallas (2026-11-14) gave six Babson players the names of Rhodes players with the same jersey numbers. `crew_named()` drops a line whose name fits the other roster and not its own. Those players' lines then appear under neither team.
- Every Sidearm site has a stats page that names a client.
- A women's schedule page can link the host's men's folder. On 2026-11-11, Alvernia's page sent its game at Ursinus to `ursinusathletics.com/sidearmstats/mbball`. The card said "no live stats" while `wbball` held the final. `womens()` maps an `mbball` folder to `wbball` in every link read.
- A client's feed answers 404 until its first game of the season starts. A school whose crews use StatBroadcast may never have one. So a 404 before tipoff gives no information. `house_feed()` uses the host's feed without reading it first.
- A tournament host runs its own game on `wbball` and the other game on `wbball2` (Hope, 2026-11-07). The schools' pages can link either folder until the hour before tipoff. When a feed shows another game after tipoff, the page and the finals pass try the host's other folders (`sibling_feeds()`, `siblingFeeds()`). They adopt the folder that shows the game.
- A neutral game at a third school takes that school's listing of it first ("SUNY Cobleskill vs. Christopher Newport" on Susquehanna's page, `host_listings()`). Next comes a page link to a site that is neither team's own, then either team's own link. On 2026-11-07, Christopher Newport's page linked its own idle feed for its game at Susquehanna.
- Every other feed the pages gave is kept as `alt_feeds`. The page and the finals pass try those after the host's other folders.
- Newer sites also serve one game at `<site>/api/livestats?game_id=<n>`, with CORS on some sites and not others. `LIVE_JS` does not use it.

Presto feeds:

- The fetcher uses a Presto feed only when the live stats link points at prestolivestats.com. The school-hosted `boxscores/*.xml` links are HTML pages without CORS.
- Many Presto rows link a short link on the school's own site that redirects to the stats page (`gocobbers.com/links/rsensu`, Concordia (MN) vs Minnesota Morris, 2026-11-11).
- The Mac's run resolves each short link of a game in its window once (`short_target()`). That takes one paced request and does not follow the redirect. The run stores the target in the cache's `links` map. Every link reader checks that map (`unshorten()`). Until the Mac resolves the short link, the game has neither a feed nor a box score page.

### Presto box score pages

- The page serves HTML despite the `.xml` name, with no CORS, so only the fetcher reads it. It updates during the game.
- Until the Mac's copy of the page gives a score, the card says "stats on Presto" (`statsLabel()`).
- The date line can run a day ahead (UTC), so the date comes from the link.
- Player cells come as `F 5 Marissa Nudd` or `25 - Long,Caroline - F`. Most mark the name with `.player-name`.
- Every Presto site answers 405 to the runner since 2026-11-07. The Mac's copy in `data/presto_cache.json` replaces the live page.
- A link can return 404 (Fitchburg St., 2026-11-06). The opponent's page link is then the fallback.

### Sidearm hub feed

- The hub is open JSON with CORS open. It answers only for about yesterday through tomorrow.
- Team sites do not always match ours. SUNY Geneseo uses knights.geneseo.edu. Binghamton uses binghamtonbearcats.com, while the NCAA directory has bubearcats.com.
- So `hub_teams()` falls back to the live stats link's site, which belongs to the school that posted the listing (`location.han` "A" means the away team). Then it falls back to the name. Games added from the hub use sites only.
- D3 pages often omit an exhibition at a Division I school (Spalding at Bellarmine, 2026-10-29). So the hub can add a game for any D3 team.
- A listing can name the wrong opponent. On 2026-10-28 Indiana listed "Marian" with the site and school ID of Marian of Wisconsin. Marian of Indiana (NAIA) listed the same game.
- A team that the hub puts against two different `school_global_id` values that day adds no game.
- Exhibition marks are in `game_promotion_name` ("Exhibition", "Scrimmage") or on a team name.
- The hub skips listings with status "C".
- A TBA game shows midnight UTC on its date.
- A stat crew can leave a template's team name in the feed. Butler's feed named Columbia as the visitor for the Franklin game. The visitor ID was `FRA`.

### ESPN

- CORS is open. The scoreboard has no exhibitions.
- A team outside Division I has `conferenceId` null and `isActive` false.
- Names are ESPN's ("Rose Hulman", "Colby Sawyer"), so a match needs an exact name.
- ESPN adds a game only for a D3 team whose page could not be read. The host's schedule page must also link that D3 team's site that day.
- ESPN gives a feed to a D1 game with no other feed (hosts that use StatBroadcast).

### StatBroadcast

- Cloudflare blocks scripted requests, the data calls need per-session tokens, and there is no CORS.
- Rows show the link only. From tipoff the card says "stats on StatBroadcast" (`statsLabel()`). Without it, the card would say "no live stats" 45 minutes after tipoff.
- The final comes from the Sidearm box score page afterward.

## Refresh chores

- After each simulation rerun or roster update, run `uv run python export_scoreboard_inputs.py` in `~/projects/d3-bball-npi`. Then commit and push The D3 Stat Lab.
- When a school changes its site or a team joins, update `team_base_websites.csv` in `d3-bball-npi`. Then run `python3 tools/make_schools.py` here.
- Schools change divisions, so run `python3 tools/make_ncaa_members.py` each fall.
- A known D1 or D2 game can be missing. No page lists it, it is an exhibition on a blocked team's schedule, or the hub does not list it yet. Then add it to `data/extra_games.json` with `division`, `d3`, and `tip`.
- `make_schools.py` keeps only the teams in `2027/teams_mapping.txt`. Change `SEASON` there each fall.

## Refresh

### Schedule

- GitHub Actions runs `fetch_data.py` and `build_site.py` at 6 a.m., noon, and 4 p.m. Eastern standard time (`7 11,17,21 * * *`).
- It also runs them at 2:37 a.m. from November through March to record finals (`37 7 * 11,12,1,2,3 *`).
- On game nights in that season it runs `fetch_data.py --finals` every 20 minutes from 6 p.m. to 1 a.m. Eastern standard time. On weekends the finals pass also runs in the afternoon from noon.
- The finals pass records finals, box score lines, and live score snapshots from Presto box score pages. It reads only the schedule pages those games need, in about 80 seconds.
- The pass also takes a live stats link that a schedule page added or changed after the last full run (`refresh_feed()`). Schools post the link on game day. A new link counts when the game had no feed, or when the new link is on the same site as the old one.

### Dispatch from the Mac

- GitHub started the 4 p.m. run 3 hours 44 minutes late on 2026-11-06 and never started the 20-minute runs. It started the 6 a.m. run at 9:17 a.m. on 2026-11-07.
- So the Mac starts every run by dispatch. `tools/dispatch_finals.sh` runs through launchd every 20 minutes.
- The script dispatches a full run once in each daily hour: 6 a.m., noon, and 4 p.m. Eastern standard time, plus 2 a.m. in season.
- It dispatches a finals pass every 20 minutes on game nights. It also dispatches one when a game in the live slates tipped off 30 minutes to 4 hours ago without a final (Saturday afternoon tournaments).
- Before each run, the script pulls the runner clone `~/projects/tonight-d3wbb-runner`, runs `fetch_data.py --presto` there, and pushes `data/presto_cache.json`.
- The cron stays as a backup for when the Mac sleeps.
- When two runs write at once, the later run's generated files win the rebase.

### Presto reads

- The Mac's `fetch_data.py --presto` reads Presto pages one at a time, 10 seconds apart, and at most 45 a run (`PRESTO_PACE`, `PRESTO_BUDGET`).
- It reads in this order:
  1. the schedule pages of Presto schools with a game in the window
  2. those games' box score pages
  3. the other schools
- Presto's AWS WAF answers a JavaScript challenge after about six requests a minute from one address. On 2026-11-08, twelve parallel reads got a challenge on every box score page.
- `get()` raises on a challenge. A challenge shows as status 202, an `x-amzn-waf-action` header, or a short page that loads `challenge.js`. The cache keeps the last copy of a page that fails.
- Presto's newer page template (SUNY Delhi, Curry, Eureka, 2026-11-08) serves empty tables. It loads the box from the school's own `/action/sports/liveupdate?e=<event>&h=<hash>` JSON. That JSON is the "Basketball LiveStats In-Arena Tool" export with status, linescore, and player lines. It has no CORS, so the browser cannot read it.
- `pt3_source()` finds the hash in the page's `conf` block. `pt3_box()` turns the JSON into the same box dict, as a second paced request.

### In the browser

- Live scores do not come from the cron. The page reads each game's feed in the viewer's browser.
- An open page rereads tonight's slate every 10 minutes to get new finals and links.
- Crews start feeds late. On 2026-11-08, La Verne, UMass Dartmouth, Hollins, and Smith showed nothing 9 minutes after tipoff. So a card whose feed does not show its game yet checks every 5 minutes for 45 minutes after tipoff, whatever its interest.
- After that the card checks every 10 minutes until 4 hours after tipoff. A tournament host's feed shows the earlier game first.
- The host's feed can move on to another game that day (Susquehanna's doubleheader, 2026-11-07). Then the card goes to Final as "Final pending". It does so at once if this browser saw the game live, and otherwise 2 hours after tipoff. It takes its score from the slate once a schedule page links the box score. Sidearm keeps no copy of the earlier game, so nothing else can supply it sooner.
- Only a feed side that names a team other than ours means the feed moved on.
- A feed that names both our teams but lists other players in the box score is a bad read. The card keeps its last score. An ended game keeps checking every 10 minutes until 4 hours after tipoff, so it comes back when the feed shows it again.
- On 2026-11-13, York (PA)'s feed alternated between Mary Washington at York and a 97-51 game with other players. An ended game stopped checking then, so one such read froze the card at "Final pending". That case led to the rule above.
- A final that the browser reads from a feed stays in that browser for 4 days. So a reload keeps the game final after the feed moves on to the host's next game.
