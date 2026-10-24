# Diagnosis Views, Schedule and Predictions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Help a fan diagnose what a team is good and bad at, see which players
drive it, and put it in league context. Add a Schedule page and a much
simpler Predictions page.

**Architecture:** see `docs/superpowers/specs/2026-10-23-diagnosis-views-schedule-design.md`.

- **Phase A (Tasks 1-3):** new dbt marts and data-layer functions. They are
  merged and **published by a real refresh before Phase B merges**: expand
  then contract.
- **Phase B (Tasks 4-11):** the pages.
- **Code layout:**
  - pure logic in `dashboard/lib/diagnosis.py`;
  - charts in a new `dashboard/lib/viz_diagnosis.py` (`viz.py` is already
    ~1,000 lines);
  - `views/players.py` and `views/teams.py` become packages, because they
    gain tabs.

**Tech stack:** Python 3.12, Streamlit, plotly, pandas, DuckDB, dbt-duckdb.

## Global Constraints

- Work only in the worktree `C:\Users\haiaj\Code\worktrees\bip-maintainability`,
  on branch `insights`.
  - Interpreter: `.venv\Scripts\python.exe` (3.12).
  - Never push. Never touch `C:\Users\haiaj\OneDrive\...` or
    `C:\Users\haiaj\bip-data`.
- Commits: a human-style subject under 72 characters, a body that explains
  why, **no Co-Authored-By or AI trailer, no emoji**.
- Code:
  - Comments explain why and match the surrounding density. Docstrings on
    public functions.
  - No new dependencies.
  - The dashboard imports only `core` and `dashboard` (enforced by
    `tests/test_import_boundaries.py`).
  - SQL is written out in full: no `.replace()`, `.format()` or
    concatenation.
- Data:
  - Numbers live in dbt marts (single source of truth). The dashboard data
    layer (`dashboard/lib/data/`) only selects and aliases.
  - Warehouse changes are additive.
  - **Pages must degrade gracefully when a new mart is absent** (an older
    published warehouse, or a Streamlit hot update): check with
    `data.core.objects_exist(...)` and show one `st.info` line, never an
    exception.
- UI:
  - Reuse the site's language: `theme` tokens (`T.ACCENT`, `T.MUTED`,
    `T.INK`, `T.INK_2`, `T.BORDER`, `T.GOOD`, `T.CRITICAL`, `T.rgba`,
    `T.team_color`), `T.card_html`, `T.kpi`, `T.chip`, `T.tip`, and
    `lib.tables.html_table` for read-only tables.
  - Every stat label gets a glossary hover (`glossary.TERMS`). Add terms
    where missing.
  - Plotly charts use `viz._layout(...)` and `viz.PLOTLY_CONFIG`.
  - Layouts work at phone width.
  - Clean beats dense: each section answers one question with one sentence
    of caption at most.
- Every task ends green:
  - `.venv\Scripts\ruff.exe check .`, `ruff format --check .`,
    `.venv\Scripts\mypy.exe`;
  - `.venv\Scripts\python.exe -m pytest -q` (634+ today; it must not drop);
  - `dbt build --profiles-dir .` from `dbt/basketball_intelligence` when dbt
    changed;
  - the **CI-style fixture run**: a scratch copy of the repo files, with
    `data/fixtures/*` copied into its `data/raw`, `scripts/load_to_duckdb.py`
    and `dbt build` into a temp warehouse via `BIP_WAREHOUSE`, then
    `CI=1 pytest -m "not full_warehouse"` with zero skips. Remove the scratch
    copy afterwards.
- Page tasks also run an AppTest render of every touched page and take
  Playwright screenshots, and visually check them.
  - Run `.venv\Scripts\python.exe -m streamlit run dashboard/app.py` on a
    spare port.
  - Drive the browser with
    `C:\Users\haiaj\OneDrive\Desktop\Coding Projects\Portfolio\Sports\basketball-intelligence-platform\.venv-314-backup\Scripts\python.exe`,
    which has Playwright, using `channel="msedge"`.
  - Save screenshots under
    `C:\Users\haiaj\AppData\Local\Temp\claude\c--Users-haiaj-OneDrive-Desktop-Coding-Projects-Portfolio-Sports-basketball-intelligence-platform\157f10cd-e6a5-4f8c-9c07-aa233e40dc60\scratchpad\insights\`.
  - Stop the server afterwards.

---

## Phase A: data (merge and publish before Phase B)

### Task 1: `mart_team_profile`

**Files:**
- Create `dbt/basketball_intelligence/models/marts/mart_team_profile.sql`.
- Modify `_marts_models.yml` and `dbt/.../tests/assert_marts_not_empty.sql`
  (add the model).
- Create the singular test `assert_team_profile_ranks.sql`.
- Tests in `tests/test_db_metrics.py` (or a new `tests/test_team_profile.py`).

**Grain:** season × team (`season`, `team_id`, `team_abbreviation`). One row
per team-season in `mart_team_season`.

**Columns:**

| Kind | Columns |
|---|---|
| Values (from `mart_team_season` where present) | `offensive_rating`, `defensive_rating`, `net_rating`, `pace`, `effective_fg_pct`, `turnover_pct`, `offensive_rebound_pct`, `free_throw_rate`, `assist_pct`, `opp_effective_fg_pct`, `opp_turnover_pct`, `defensive_rebound_pct`, `opp_free_throw_rate` |
| New values (from team game logs plus the opponent join) | `three_pt_pct` (team 3PM / 3PA × 100), `three_pt_rate` (3PA / FGA × 100), `opp_three_pt_pct`, `opp_three_pt_rate` |
| Ranks | For each value `x`: `x_rank` (integer, 1 = best in that season's league) |
| Percentiles | `x_pctile` (0-100, 100 = best) |

- **Source for the new values:** `main_intermediate.int_team_game_opponent`,
  or the staging team game logs with the opponent side. Read the models and
  reuse their joins.
- **Direction (better = rank 1):**
  - higher is better for offensive rating, eFG%, 3P%, offensive rebound %,
    free throw rate, assist rate, opponent turnover rate and defensive
    rebound %;
  - lower is better for defensive rating, turnover rate, opponent eFG%,
    opponent 3P% and opponent free throw rate.
- **Pace and 3-point rates** are "style": rank by highest value, and
  document that rank 1 = most, not best.
- **Rank and percentile:**
  - `rank() over (partition by season order by x [desc|asc])`;
  - `percentile = 100 * (1 - (rank - 1) / (teams_in_season - 1))`;
  - ties share a rank;
  - a null value gives a null rank and percentile.
- **Tests:**
  - `unique`/`not_null` on the grain;
  - `assert_team_profile_ranks`: every non-null rank is in 1..teams that
    season, every percentile in 0..100, and the direction check (the team
    with the lowest `turnover_pct` in a season has `turnover_pct_rank = 1`;
    the highest `offensive_rating` has rank 1);
  - the new 3P values match a direct computation from game logs for one
    season (pytest on the real warehouse; also runs on fixtures);
  - the not-empty list includes the model.
- **Commit:** "Rank every team stat within its season in mart_team_profile".

### Task 2: `mart_player_percentiles` and `mart_player_defense`

**Files:**
- Create `mart_player_percentiles.sql` and `mart_player_defense.sql`.
- Update the yml, the not-empty test and pytest.

**`mart_player_percentiles`** (grain: season × player):
- **Qualified players:** those meeting the dashboard's qualification rule,
  moved into SQL. Read `dashboard/lib/stats.py::qualification_threshold`.
  Port it faithfully, with a comment pointing back at it. The Python function
  stays, but gains a docstring line saying the mart mirrors it, plus a test
  asserting both give the same threshold for 3 seasons.
- **Measures** (each with `_pctile` 0-100 among that season's qualified
  players, higher = better):
  - `points_per_game`, `true_shooting_pct`, `rebounds_per_game`,
    `assists_per_game`, `steals_per_game`, `blocks_per_game`,
    `threes_made_per_game`;
  - ball security: `turnover_pct`, inverted so a lower turnover rate gives a
    higher percentile;
  - `usage_pct`, `assist_pct`, `rebound_pct`, `offensive_rebound_pct`,
    `defensive_rebound_pct`, `steal_pct`, `block_pct`, `free_throw_rate`.
- **Percentile:** `100 * percent_rank()` within the qualified set, direction
  aware. Non-qualified players get null percentiles but keep their row and an
  `is_qualified` flag.

**`mart_player_defense`** (grain: season × player):
- **Columns:**
  - `team_abbreviation`;
  - `minutes`;
  - `games_played`;
  - `on_court_def_rating`: the player's official `defensive_rating` from
    `mart_player_season`, 1996-97 on;
  - `team_def_rating` and `team_games`: from `mart_team_season` for his team;
  - `minutes_share = minutes / (team_games * 48)`;
  - `est_off_court_def_rating = (team_def_rating - minutes_share * on_court_def_rating) / (1 - minutes_share)`;
  - `def_on_minus_off = on_court_def_rating - est_off_court_def_rating`;
  - `fouls_per_36`: personal fouls per 36 minutes from game logs (check the
    staging column name for personal fouls).
- **Null rules:**
  - the on/off columns are null unless all of these hold: the season was
    with a single team (`team_label` has no `→`), `minutes >= 500`, the
    season is 1996-97 or later, and `minutes_share < 0.95`;
  - `fouls_per_36` is null when `minutes < 100`.
- **Tests:**
  - grain;
  - `def_on_minus_off` is null exactly when the rules say so;
  - a numeric check against the hand calculation for 2024-25 BOS Jrue
    Holiday (on 107.7, team 110.1, share 0.48 → about -4.6, tolerance 0.2;
    mark the pytest `full_warehouse` if the fixture lacks him);
  - `fouls_per_36` in 0..15.
- **Commit:** "Add player percentile and defensive on/off marts".

### Task 3: Data layer for diagnosis and the schedule

**Files:**
- Create `dashboard/lib/data/diagnosis.py`, `dashboard/lib/data/schedule.py`,
  `dashboard/lib/diagnosis.py` (pure logic),
  `tests/test_data_diagnosis.py`, `tests/test_data_schedule.py` and
  `tests/test_diagnosis.py`.

**`dashboard/lib/diagnosis.py`** (pure, no Streamlit, no SQL):
- `ProfileStat` is a NamedTuple:
  `key, label, group ("Offense"|"Defense"|"Style"), glossary term`.
- `PROFILE_STATS: list[ProfileStat]`, in the spec's order:
  - **Offense:** offensive rating, eFG%, 3P%, 3-pt rate, turnover rate,
    off. rebound %, FT rate, assist rate;
  - **Defense:** defensive rating, opp eFG%, opp 3P%, opp turnover rate,
    def. rebound %, opp FT rate;
  - **Style:** pace.
- `Measure` is a NamedTuple `col, label, term, kind` (kind: pct, share,
  ratio, num or signed), with `format(value)` as the one place values print.
- `Area` is a NamedTuple:
  `key, label, team_stat, team_rank_col, measures (list[Measure]), defensive (bool), caption`.
  `AREAS: list[Area]` is the spec's table, all 10 areas, including "Defense
  on/off (estimate)" and "Fouling".
- No generated sentences: `summary_line` and `driver_read` were built in
  Task 3 and removed in Task 5, because the owner wants evidence, not
  verdicts.

**`dashboard/lib/data/diagnosis.py`:**
- `profile_available() -> bool` (`objects_exist` for the three new marts).
- `team_profile(season) -> pd.DataFrame` (all columns).
- `team_drivers(season, team) -> pd.DataFrame`:
  - the rotation for that team-season: players with 10+ games for the team,
    from `mart_player_team_season`;
  - joined to `mart_player_season` rates, `mart_player_percentiles` and
    `mart_player_defense` on (season, player_id);
  - columns: `player_id, player, games_played, minutes, minutes_per_game,
    three_pa_per_game, fg3_pct, team_three_pa_share` (the player's 3PA ÷ the
    team's 3PA, computed in SQL), plus every measure `AREAS` needs;
  - plus the league medians for each measure in that season, as
    `<col>_league_median` columns (constant per frame), computed in SQL over
    qualified players.
- `player_percentiles(season, player_id) -> pd.Series | None`.
- `league_player_rows(season, min_games) -> pd.DataFrame`: the scatter source.
  Every scatter metric column for players with `games_played >= min_games`,
  plus `team` and `team_label`.

**`dashboard/lib/data/schedule.py`** (existing published objects only):
- `schedule(season) -> pd.DataFrame`:
  - one row per regular-season game from `main_staging.stg_schedule`;
  - left-joined to `main_marts.fct_team_game` for the result, and to the
    latest prediction per game (reuse `data.predictions`' logic, or the
    `predictions` table with the same latest-per-game rule; don't duplicate
    the settled SQL);
  - columns: `game_id, game_date, tipoff_utc, home, away, home_id, away_id,
    home_points, away_points, is_final, win_probability (home),
    predicted_margin, top_scorer, top_points`;
  - `top_scorer`/`top_points` come from the player game logs: the game's
    highest scorer, ties broken by name.
- `month_counts(season, year, month) -> dict[date, int]`.
- `team_schedule(season, team) -> pd.DataFrame`: that team's games, with
  `opponent`, `is_home`, `result` ("W 112-105" / "L …" / ""), and a running
  `record`.
- **Tests:** on a synthetic warehouse built with `use_warehouse` (follow
  `tests/test_player_search.py`'s pattern) plus the real one: counts, a
  finished game's score and top scorer, an upcoming game's probability,
  running record, an empty month.
- **Commit(s):** "Add the diagnosis rules and their data layer", "Add a
  schedule data layer".

**After Task 3 (controller):** PR + Linux CI, merge Phase A to main, run a
real publishing refresh, and confirm the three marts exist in the published
warehouse. Then start Phase B.

## Phase B: pages

### Task 4: Teams package and the league-ranks profile

**Files:**
- Convert `dashboard/views/teams.py` into the package
  `dashboard/views/teams/`, with an unchanged public `render()`:
  - `__init__.py`: render, tabs;
  - `team.py`: the Team tab, with today's sections minus Four Factors;
  - `standings.py`;
  - `profile.py`.
- Add `profile_chart(profile_row) -> go.Figure` to `dashboard/lib/viz_diagnosis.py`.
- Update `dashboard/app.py` only if the import changes. Update tests.

- **Profile section:** placed where Four Factors was, titled "How they rank
  in the league". A heading with a glossary tip, then the chart; no summary
  line.
- **Chart:** horizontal bars, one per `PROFILE_STATS` row, grouped with group
  labels.
  - Bar length = percentile (0-100), colour from `T.CRITICAL` (percentile 0) through
    neutral to `T.GOOD` (percentile 100).
  - Text on the bar: value (formatted per stat) and `#rank`.
  - Style rows in `T.MUTED` with "most/least" wording.
  - A dashed line at 50 (league median).
  - Height scales with rows. No legend.
- **Fallback:** when `diagnosis.profile_available()` is false, keep showing
  the old Four Factors cards (move that code into `profile.py`'s fallback)
  with one `st.info` line.
- **Delete** the old Four Factors section from the Team tab.
- **Tests:** AppTest of the Team tab on the real warehouse; on a warehouse
  without the marts, the fallback shows and nothing raises; `profile_chart`
  unit test (row count, colours by percentile, labels).
- **Commit:** "Show where each team ranks in the league on every key stat".

### Task 5: Player breakdown

**Files:**
- Create `dashboard/views/teams/breakdown.py`.
- Add `drivers_chart(rows, area, team) -> go.Figure` to `viz_diagnosis.py`.
- Navigation helper: `dashboard/lib/nav.py`, plus app.py registering pages
  into it. Tests.

- **Section:** "Player breakdown", below the profile.
  - A `segmented_control`/selectbox over `AREAS` labels. Default: the first
    area.
  - A chip with the team's rank in the area.
  - No generated sentence; a compact table of the numbers (player, minutes,
    measures, league median) under the chart.
  - The chart: one row per rotation player, the measure as a dot or bar
    against a vertical league-median line, marker size by minutes, team
    colour, sorted by minutes.
  - The area's caption. Defensive areas say plainly that box scores and this
    estimate can't replace film.
- **Click-through:**
  - Under the chart, a compact row of player buttons ("Open on Players →",
    one per rotation player; or a selectbox plus button if more than 8).
  - Clicking sets `st.session_state[state.PLAYERS_PICK_KEY]` and the season,
    then switches to the Players page through `nav.go("players")`.
  - `dashboard/lib/nav.py` keeps a registry `{name: st.Page}` that app.py
    fills: `nav.register(name, page)`, `nav.go(name)` →
    `st.switch_page(registry[name])`.
  - The Players page must honour the preset pick: check that
    `views/players`' pick logic selects the preset player if present.
- **Tests:**
  - AppTest: each area renders for a real team;
  - no verdict wording appears;
  - clicking a player button sets the state keys (switch_page can be
    monkeypatched in the test);
  - the defensive areas show their caption;
  - a pre-1996 season shows on/off as unavailable without error.
- **Commit:** "Add a player breakdown for each team stat area".

### Task 6: Any-two-stats team scatter

**Files:**
- `dashboard/views/teams/team.py`, where the chart section lives.
- Add `stat_scatter(df, x, y, label_col, color_col, highlight=None, x_label=..., y_label=..., label_top=12, invert=())`
  to `viz_diagnosis.py`. It's generic and Task 8 reuses it.
- Remove `viz.rating_quadrant` if nothing else uses it (grep).

- **Section:** two selectboxes over the profile stats.
  - Default: offensive rating (x) vs defensive rating (y), with the y axis
    inverted so up = better defence, and quadrant captions kept (port the
    existing quadrant labelling).
  - Dots in team colours, the selected team highlighted (bigger, outlined),
    dashed league-average lines.
  - Hover shows the team, both values and both ranks.
- **Tests:** a `stat_scatter` unit test (point count, highlight trace, average
  lines, label count capped); AppTest with a non-default pair.
- **Commit:** "Let the team scatter compare any two stats".

### Task 7: Players package; the Stats tab gets a game log and any-stat trend

**Files:**
- Convert `dashboard/views/players.py` into the package
  `dashboard/views/players/`:
  - `__init__.py`: render plus tabs Stats / Scatter / Compare;
  - `stats.py`: today's page;
  - `scatter.py` and `compare.py`: stubs that Tasks 8-9 fill. A stub renders
    one caption line.
- Add `stat_trend(games, stat) -> go.Figure` to `viz_diagnosis.py`, or
  generalise `viz.player_trend` (prefer replacing `player_trend` if only
  Players uses it).
- Tests: all existing Players tests stay green, with imports updated.

- **Game log** (season detail): an `html_table` with these columns:
  - date, opponent (`vs`/`@` plus code), result (`W`/`L` and score), MIN, PTS,
    REB, AST, 3PM, TS% (per game; "-" when there are no attempts), +/-;
  - each stat cell tinted green or red against his season average (± a small
    band, about 15%, for "normal") using `T.rgba(T.GOOD/T.CRITICAL, 0.18)`
    backgrounds;
  - newest first, all games, inside a fixed-height scroll container.
- **Trend:** a stat picker (PTS, REB, AST, 3PM, TS%, +/-). Bars per game plus
  a 5-game rolling line and a dashed season-average line. It replaces the
  points-only trend.
- **Preset pick:** honour `state.PLAYERS_PICK_KEY` set by Teams (Task 5) or
  Schedule.
- **Tests:** AppTest on Luka Dončić 2025-26: the game log has 64 rows; the
  picker switches the chart title; `stat_trend` unit test; a preset pick
  opens that player.
- **Commit:** "Give player detail a coloured game log and any-stat trend".

### Task 8: Players Scatter tab

**Files:** `dashboard/views/players/scatter.py`, tests.

- **Controls:**
  - season (default: the sidebar's);
  - x and y selectboxes over a curated metric list (defaults: points per game
    vs TS%). The list: PTS, REB, AST, STL, BLK, 3PM, TS%, eFG%, USG%, AST%,
    REB%, TOV%, STL%, BLK%, 3PA rate, FT rate, +/-, PIE, game score, minutes;
  - min games (default `stats.qualification_threshold`);
  - team (All, or one team: highlights it and labels all its players).
- **Chart:** `stat_scatter`, with the ~12 farthest-from-average players
  labelled and hover showing the stat line. Caption: n players, the filters.
- Glossary help on every metric label.
- Data: `data.diagnosis.league_player_rows`.
- **Tests:** AppTest renders, changing an axis changes the chart, the team
  filter highlights.
- **Commit:** "Add a player scatter of any two stats".

### Task 9: Players Compare tab

**Files:**
- `dashboard/views/players/compare.py`.
- Add `compare_radar(a_row, b_row, labels)` and `compare_bars(...)` to
  `viz_diagnosis.py`, or reuse `viz.compare_dumbbell` if it fits. Tests.

- **Pickers:** two player-season pickers, each a search text input plus a
  selectbox of matches. Use `data.players.player_latest_seasons` and the
  season list for the chosen player; any era.
  - Defaults: the two top scorers of the current season.
- **Charts:**
  - A radar of 8 percentile measures from `mart_player_percentiles`: scoring
    (PTS), efficiency (TS%), rebounding (REB%), playmaking (AST%), ball
    security (TOV%, inverted), steals (STL%), blocks (BLK%), 3-point volume
    (3PM). Each player is in his team colour. If both have the same colour,
    the second gets `T.ACCENT`.
  - Side-by-side stat bars for the per-game line (`compare_dumbbell` style).
- **Caption:** percentiles are within each player's own season's qualified
  players, so eras compare fairly. A non-qualified player-season shows its
  stats with "not enough games for percentiles".
- **Tests:** AppTest, both pickers, a non-qualified case, a pre-1996 player
  (no advanced: radar shows the available axes only, without error).
- **Commit:** "Add a head-to-head player compare".

### Task 10: Schedule page

**Files:**
- Create `dashboard/views/schedule.py`.
- `dashboard/app.py`: register the page after Games (`url_path="schedule"`,
  icon `:material/calendar_month:`) and in `nav`.
- `dashboard/views/games.py`: honour a preset game pick.
- `dashboard/lib/state.py`: `GAMES_PICK_KEY`.
- Tests.

- **Header:** "Schedule" with the season chip, a team selectbox (All teams /
  each team) and month arrows (`◀ October 2026 ▶`, kept in session state;
  default: today's month if within the season, else the season's first
  month).
- **Calendar:** a 7-column grid of `st.button`s, Sun-Sat.
  - Each label is the day number plus the game count ("23 · 12 games"), or
    with a team selected "23 · vs BOS" / "@ BOS" / blank.
  - Days outside the month are empty placeholders.
  - The selected day uses `type="primary"`; today is marked.
  - Keys are stable and unique.
- **Day view** (below the calendar): the date heading, then compact rows built
  with `html_table`:
  - Finished games: `NYK 105 @ BOS 112 · Final · Tatum 34` plus an "Open
    game" button per row. The button sets `state.GAMES_PICK_KEY` = game_id
    and the season, then `nav.go("games")`.
  - Upcoming games: `7:00 PM ET · NYK @ BOS · BOS 65%` (favourite bold in its
    colour, probability once).
  - An empty day says "No games."
- **With a team selected:** below the day view, that team's full season from
  `data.schedule.team_schedule` (date, opponent, result or tip-off, record)
  as a compact table.
- **Games page:** if `state.GAMES_PICK_KEY` is set, pick that game in its
  selector (and the season), then clear the key.
- **Tests:**
  - AppTest: the calendar renders for October 2026 with the right counts;
  - clicking a day shows its games;
  - the team filter changes cell labels;
  - "Open game" sets the keys (monkeypatch switch_page);
  - the Games page honours the preset;
  - an empty day;
  - the offseason month.
- **Commit:** "Add a Schedule page with a calendar and team schedules".

### Task 11: A simpler Predictions page

**Files:** `dashboard/views/predictions.py` (rewrite the render path),
`dashboard/lib/viz.py` (only if the calibration chart helper needs a tweak),
tests.

- **Upcoming:** next 7 days, grouped by date heading. One `html_table`-style
  compact row per game, four columns: tip-off (ET) · matchup (favourite bold
  in its team colour inside `AWY @ HOM`; the abbreviation never repeated) ·
  probability (`65%` plus a thin single-colour bar in the favourite's colour
  scaled 50→100%; "toss-up" in place of the bar under 55%) · margin
  (`by 5`).
  - About 36 px per row.
  - A caption links to the Schedule page for later dates.
- **Track record:** one KPI row (accuracy, Brier score, margin error) with the
  existing glossary tips. "Settled games: N" as the KPI sub-line.
- **Details:** one collapsed expander, "How the model works and how
  well-calibrated it is", containing today's explainer text and the
  calibration chart (when 50+ settled games).
- **Recent results:** the 10 most recent settled games, compact: matchup ·
  pick · probability · final · ✓/✗.
- **Delete** `prediction_card` and the two-colour bar code if unused.
- **Tests:** update `tests/test_predictions_page.py`: row count per day, no
  repeated favourite abbreviation in a row, the toss-up label, the expander
  contains calibration when available, the empty states (no upcoming / no
  settled) still work.
- **Commit:** "Make the Predictions page a compact list".

### Task 12: Docs and screenshots

**Files:** `README.md` (pages list and features; new screenshots for Teams,
Players, Schedule and Predictions under `site_pictures/`), `CONTRIBUTING.md`
(only if commands changed), `docs/architecture.excalidraw` (add the Schedule
page and the three marts), glossary terms already added, ADR 0006 (add the
"defensive on/off is an estimate" limitation).

- Retake the screenshots with Playwright: the same 1500-px full-page style as
  the existing `site_pictures`, against the worktree app.
- **Commit:** "Document the diagnosis views, schedule and predictions".
