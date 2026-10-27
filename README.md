# Tonight in D3 WBB

Live scores for every Division III women's basketball game that counts for the NPI, plus D3 games against Division I and II teams, sorted by how interesting each game is right now. `PLAN.md` holds the design: the interest score, the win probability model, the check schedule, and the newcomer rules.

## Files

| File | Purpose |
|------|---------|
| `site.json` | Name, domain, analytics code, time zones, accent colors |
| `fetch_data.py` | Builds `data/slates/YYYY-MM-DD.json` for today and tomorrow, records finals and newcomer lines for yesterday and today, and writes `data/data.json` (fetch time, errors, game count per date) |
| `build_site.py` | Renders `docs/index.html`, embeds the default night's slate, and copies the slates to `docs/slates/`. `LIVE_JS` holds the browser model and scheduler |
| `data/schools.csv` | Each school's schedule page, page type (Sidearm or Presto), and time zone. Written by `tools/make_schools.py` |
| `data/ncaa_members.csv` | Every NCAA school with women's basketball: name, division, conference, athletics site. Written by `tools/make_ncaa_members.py` |
| `tools/make_ncaa_members.py` | Rebuilds `data/ncaa_members.csv` from the NCAA directory |
| `data/extra_games.json` | Games the schedule pages miss, such as a D3 exhibition at a Division I school on a page the reader cannot parse. The file's `note` lists the fields |
| `tools/make_schools.py` | Rebuilds `data/schools.csv` from `~/projects/d3-bball-npi` (`team_base_websites.csv`, `school_demographics.csv`) |
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
| Sidearm schedule pages | Tipoff, home or away, live stats link | Times often print with no zone, so each school's zone comes from `data/schools.csv`. The home page sometimes lists a game with no time while the away page has it. Conference-hosted pages (Penn St. Brandywine on gounitedeast.com) use the older table layout with no live stats links; `sidearm_table_rows()` reads them |
| Presto schedule pages (47 schools) | Same | At least three templates (cards, newer cards, tables). Every template puts "Women's Basketball event: November 14 02:00 PM: ..." in each link's `aria-label`. Source URLs name the 2025-26 season; `season_url()` swaps in 2026-27. Some sites sometimes return a 200 page with no games; the fetcher reads it a second time. On 2026-10-26, 45 of the 47 Presto sites answered scripted requests with an AWS WAF bot challenge (Austin returned 403, VTSU Johnson 404), so their games took tipoff and feed from the opponent's page. Huntingdon uses a template the reader does not parse |
| NCAA directory `web3.ncaa.org/directory/api/directory/memberList?type=12&sportCode=WBB` | Each NCAA school with women's basketball: division, conference, athletics site | Open JSON, about 1.3 MB. Sidearm schedule rows link the opponent's athletics site, which matches the directory's `athleticWebUrl`; Presto rows have no such link, so those match by name and only when one school fits. NAIA and two-year schools are not in it |
| Sidearm feed `sidearmstats.com/<client>/wbball/game.json` | Score, period, clock, `IsComplete` (about 4 KB) | CORS open. Holds the client's latest game, so the page checks `Game.Date`. Player box scores only with `?detail=full` (about 300 KB) |
| Presto feed `data.prestolivestats.com/xml/<site>/events/<event>.xml` | StatCrew XML with player stats | Only when the live stats link points at prestolivestats.com. The school-hosted `boxscores/*.xml` links are HTML pages without CORS |

## Refresh chores

- After each simulation rerun or roster update, run `uv run python export_scoreboard_inputs.py` in `~/projects/d3-bball-npi`, then commit and push The D3 Stat Lab.
- When a school changes its site or a team joins, update `team_base_websites.csv` in `d3-bball-npi`, then run `python3 tools/make_schools.py` here.
- Each fall, run `python3 tools/make_ncaa_members.py`, because schools change divisions.
- When a known D1 or D2 game is missing (the D3 page does not list it, or the host's page uses Sidearm's newer template), add it to `data/extra_games.json` with `division`, `d3`, and `tip`.
- `make_schools.py` keeps only the teams in `2027/teams_mapping.txt`. Change `SEASON` there each fall.

## Refresh

GitHub Actions runs `fetch_data.py` and `build_site.py` at 6 a.m., noon, and 4 p.m. Eastern standard time (`7 11,17,21 * * *`), and at 2:37 a.m. from November to March to record finals (`37 7 * 11,12,1,2,3 *`). Live scores do not come from the cron: the page reads each game's feed in the viewer's browser.
