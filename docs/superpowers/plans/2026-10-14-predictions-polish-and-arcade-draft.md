# Predictions Polish + Arcade "Build a team" Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:**
- Make the Predictions page production quality.
- Add an Arcade mode where users build or draft an 8-man team from one
  season or from all-time, and see how it would fare in simulated seasons.

**Architecture:**
- An offline model (`ml/player_impact.py`, sklearn, run by the weekly
  refresh) scores every player-season since 1985-86 and writes a
  `player_impact` table into the warehouse.
- The dashboard reads that table. A numpy-only simulation engine
  (`dashboard/lib/sim.py`) turns rosters into net ratings and simulated
  seasons.
- `dashboard/lib/draft.py` holds the budget rules and the CPU drafting.
- The Predictions page is rebuilt from plain db queries. It must NOT import
  `ml.*`, because sklearn and scipy are dev-only.

**Tech Stack:** Python 3.12/3.14, DuckDB, pandas, numpy, scikit-learn (offline only), Streamlit 1.58, Plotly, pytest + `streamlit.testing.v1.AppTest`.

**Spec:** `docs/superpowers/specs/2026-10-14-predictions-polish-and-arcade-draft-design.md`, read it first.

## Global Constraints

- **Commits:** human-style messages, **no `Co-Authored-By` trailers**, no emoji. Commit only the files your task owns: `git add <paths>`, never `git add -A`. Other tasks may be running in parallel in the same working tree; if `git commit` hits an index.lock, wait a few seconds and retry.
- **Python:** run with `.venv/Scripts/python.exe`. Set `PYTHONIOENCODING=utf-8` when printing DuckDB results.
- **Dashboard imports:** dashboard code (`dashboard/**`) must not import `sklearn`, `scipy` or anything under `ml/`. numpy and pandas are fine.
- **Theme:** use only existing tokens and helpers in `dashboard/lib/theme.py` (`T.kpi`, `T.card_html`, `T.chip`, `T.tip`, `T.team_color`, `T.team_dot`, `.bip-*` classes). No new colors except team colors.
  - Numbers shown to users are formatted: percentages as "61%", margins as "BOS by 6", money through `payroll.money`.
  - A dollar sign in `st.markdown` text must be escaped as `\$`.
- **Glossary:** jargon gets explained through `dashboard/lib/glossary.py` `TERMS`, shown with `T.tip(...)` or `glossary.marked/described` on grid columns.
- **Old warehouses:** every page must degrade gracefully on a warehouse missing the new tables (`player_impact`, or no settled predictions): show an `st.info` line, never a stack trace.
- **Data grids:** use `st.dataframe` with `hide_index=True, width="stretch", row_height=38`.
- **Tests:** add pytest coverage as each task specifies. The full suite (`.venv/Scripts/python.exe -m pytest tests -q`) must pass before you commit.
- **Paths:** the real warehouse is `warehouse/basketball.duckdb`, gitignored and local only. CI uses fixture parquet files, so tests that need the real warehouse use the `con` fixture from `tests/conftest.py`, which skips locally if the file is missing and fails in CI.

---

### Task 1: Player impact model and `player_impact` table

**Files:**
- Create: `ml/player_impact.py`
- Create: `tests/test_player_impact.py`
- Modify: `scripts/weekly_refresh.py` (add a step after `dbt_test`, before `predict`)

**Interfaces:**
- Produces, in `warehouse/basketball.duckdb` schema `main`:
  - Table `player_impact`, one row per player per season, 1985-86 onward, eligible only if GP ≥ 40 and MPG ≥ 15. Columns:
    `season varchar, player_id bigint, player varchar, team varchar` (e.g. "CHI → BOS", in team order),
    `gp int, mpg double, ppg double, rpg double, apg double`,
    `impact double` (points per 36 vs. an average player, the model output),
    `usage double` (the usage proxy below, relative to league = 1.0),
    `cost int` (1-10).
  - Table `player_impact_meta`, a single row: `fitted_at timestamp, n_train int, holdout_corr double, team_scale double, team_offset double, team_r2 double, team_mae double, usage_league_total double`.
- Python API, so tests and the refresh can call it:
  - `STATS = ["pts","orb","drb","ast","stl","blk","tov","fga","fta","tpm","pf"]`
  - `relative_rates(df) -> DataFrame`. Input has per-row season totals of STATS plus `mins` and `season`. Output adds `<stat>_r` = per-36 rate minus that season's league per-36 rate. The league rate is the sum over all rows in that season of stat / mins × 36.
  - `fit_impact(train_df) -> (coef: np.ndarray, intercept: float)` (see the procedure below).
  - `build(con) -> (impact_df, meta_dict)`
  - `write(con, impact_df, meta_dict)`, which replaces both tables.
  - `main()`, run as `python -m ml.player_impact`. It opens the warehouse read-write, builds, writes, and prints the meta.

**Procedure (from the 2026-10-14 prototype, which gave holdout corr 0.45 and sane rankings):**
1. Player-team-season totals from `main_staging.stg_player_game_logs`, grouped by `season, team_abbreviation, player_id`:
   - `mins` = sum(minutes_played)
   - pts, orb (offensive_rebounds), drb (defensive_rebounds), ast, stl, blk, tov (turnovers), fga (field_goals_attempted), fta (free_throws_attempted), tpm (three_pointers_made), pf (personal_fouls), pm (sum(plus_minus)), gp.
2. Training rows:
   - Season ≥ '1996-97', plus-minus not null, mins ≥ 500, joined to `main_marts.mart_team_season.net_rating` on (season, team_abbreviation).
   - Target `rel_pm` = pm/mins×36 − 0.7×net_rating.
   - Ridge(alpha=5.0) on the `_r` features, sample_weight = mins.
   - Holdout: refit on all but the last 5 seasons, then report the Pearson correlation on those 5 as `holdout_corr`. The final coefficients are refit on all training rows.
3. Score every player-season (grouped by season, player_id, across teams) from 1985-86 on:
   - `impact = coef·x_r + intercept`, with `_r` computed from the player's whole-season totals.
4. Team calibration:
   - For each team-season with a net_rating (1985-86 on, via mart_team_season), compute S = Σ over that team's players of (mins_on_team / team_total_mins × 5) × impact. Use the player's season impact and his minutes for that team.
   - Fit net_rating ≈ team_offset + team_scale × S with OLS (numpy polyfit) and report R² and MAE.
5. Usage proxy:
   - `usage_raw` = (fga + 0.44·fta + tov) / mins × 36.
   - `usage` = usage_raw / league usage_raw for that season, so league = 1.0.
   - `usage_league_total` = 5.0 (five average players). Store it in meta.
6. Cost: the percentile of impact within the eligible pool across all seasons, mapped to `cost = 1 + round(9 × pct)`, clipped to 1..10.
7. `team`: the player's teams that season in order of first game, joined with " → ".

**weekly_refresh.py:** add `("player_impact", [PYTHON, "-m", "ml.player_impact"], None)` immediately after `("dbt_test", ...)`. It is fatal like the other dbt and ml steps.

**Tests (`tests/test_player_impact.py`):**
- `relative_rates`:
  - Season A has two players: P1 with mins 360 and pts 100, P2 with mins 360 and pts 20.
  - The league per-36 is 120 / 720 × 36 = 6.0.
  - P1's `pts_r` = 100/360×36 − 6 = 4.0; P2's = 2 − 6 = −4.0.
- `fit_impact` on synthetic data: build 400 rows where `rel_pm = 1.5*pts_r - 2.0*tov_r` plus small noise, and the other `_r` features are random. The fitted pts coefficient is within 0.2 of 1.5, and tov within 0.2 of −2.0.
- With the real warehouse (`con` fixture), run `build()` read-only on a connection and check:
  - The top-10 impact player-seasons include at least one of Stephen Curry, Nikola Jokić, Michael Jordan, LeBron James.
  - No Dennis Rodman season is in the top 50.
  - `team_r2 > 0.7`.
  - All costs are in 1..10.
- **Do not** write to the real warehouse in tests.

**Run once at the end:** `.venv/Scripts/python.exe -m ml.player_impact`. This writes the tables to the real local warehouse. Put the printed meta in your report.

**Commit:** `ml/player_impact.py tests/test_player_impact.py scripts/weekly_refresh.py` with the message "Score every player-season's impact for the Arcade team builder".

---

### Task 2: Simulation engine `dashboard/lib/sim.py`

**Files:**
- Create: `dashboard/lib/sim.py`
- Create: `tests/test_sim.py`

**Interfaces (pure numpy and pandas, no Streamlit):**
- Constants: `STARTER_MINUTES = 32`, `BENCH_MINUTES = 16`, `ROSTER_SIZE = 8`, `STARTERS = 5`, `GAME_SD = 12.7`, `HOME_EDGE = 2.5`, `SEASON_GAMES = 82`, `N_SIMS = 1000`, `USAGE_PENALTY = 0.5`.
- `rotation_weights() -> np.ndarray`: length 8 = [32]*5 + [16]*3 divided by 48, so the weights sum to 5.0.
- `team_net_rating(impacts, usages, scale, offset, usage_league_total=5.0) -> float`:
  1. `S = Σ w_i × impact_i`, with w from `rotation_weights()` and impacts in rotation order.
  2. `U = Σ w_i × usage_i`.
  3. `excess = max(0, U − usage_league_total)`.
  4. Penalty = `USAGE_PENALTY × excess × max(0, mean of positive impacts)`. This is the documented heuristic: too many ball-dominant players can't all use the ball.
  5. Return `offset + scale × S − penalty`.
- `win_prob(net_a, net_b, home_edge=0.0) -> float`: P(margin > 0), with margin ~ Normal(net_a − net_b + home_edge, GAME_SD). Use the math.erf normal CDF; scipy is not allowed.
- `simulate_vs_league(team_net, opponent_nets, rng, n_sims=N_SIMS) -> dict`:
  - Each sim plays 82 games against opponents drawn round-robin from `opponent_nets`, cycling through the list, with home/away alternating (+2.5 to the home side). Each game's margin is sampled from Normal.
  - The opponents also play their own 82-game seasons in each sim, simplified: each opponent's wins ~ Binomial(82, p) with p = win_prob(opp_net, mean(opponent_nets)). That gives best-record odds.
  - Returns `{"wins": np.ndarray of shape (n_sims,), "median": int, "p10": int, "p90": int, "best_record_odds": float}`.
- `simulate_season_once(team_net, opponent_nets, rng) -> dict`: one season's game-by-game list `[(opp_index, is_home, margin, won)]`, plus `wins` and `losses`.
- `simulate_league(team_nets: list[float], rng, n_sims=N_SIMS) -> dict` for Draft mode:
  - N teams (6) play a balanced round robin totalling 82 games per team. Distribute 82 as evenly as possible across opponents: some pairs meet one extra time, home/away split evenly.
  - Then playoffs: the top 4 by wins (ties broken randomly) play best-of-7 series, 1v4 and 2v3, then the final. Series are simulated game by game, with home edge to the higher seed in games 1, 2, 5 and 7.
  - Returns `{"wins": array (n_sims, N), "median_wins": array N, "title_odds": array N, "playoff_odds": array N}`.
- `simulate_league_once(team_nets, rng) -> dict`: final standings (wins per team), plus the playoff bracket as a list of series dicts `{round, high, low, high_wins, low_wins, winner}`, plus `champion`.
- `roster_seed(player_ids) -> int`: a stable seed from the sorted player_ids, e.g. `int(hashlib.sha256(",".join(map(str, sorted(ids))).encode()).hexdigest()[:8], 16)`. Used for projections, so the same roster always gets the same projection.

**Tests (`tests/test_sim.py`):**
- `rotation_weights().sum() == pytest.approx(5.0)`.
- Two identical rosters with the same seed give identical `simulate_vs_league` output. Different seeds give different `simulate_season_once` records, at least occasionally: across 20 seeds, more than one distinct win total.
- A higher team net gives higher median wins against the same league (net +8 vs net 0, league of 29 zeros).
- Against a league of 29 zeros, the mean wins for net 0 is within 41 ± 1.5 over 2000 sims. For net +5, the mean is above 50.
- `win_prob(0, 0) == pytest.approx(0.5)`; `win_prob(5, 0) > 0.6`.
- `simulate_league` with 6 teams:
  - Every team plays exactly 82 games in `simulate_league_once` (sum of wins + losses).
  - Exactly one champion.
  - `title_odds` sums to 1.0 ± 1e-9.
  - The strongest team (net +10, others 0) has the highest title odds.
- Usage penalty: the same impacts with usages summing well above 5 give a lower net than with average usages.
- `roster_seed` is order-independent.

**Commit:** `dashboard/lib/sim.py tests/test_sim.py` with the message "Add a numpy season and playoff simulator for the Arcade team builder".

---

### Task 3: Pool loader, budget rules and CPU draft (`dashboard/lib/draft.py` + db)

**Files:**
- Create: `dashboard/lib/draft.py`
- Create: `tests/test_draft.py`
- Modify: `dashboard/lib/db.py` (add 3 functions near `arcade_pool`)
- Modify: `tests/conftest.py` (add a `warehouse_with_player_impact` fixture)

**Interfaces:**
- `db.player_impact_available() -> bool`: an `st.cache_data(ttl=600)` probe of `main.player_impact` and `main.player_impact_meta`. Same try/except pattern as `team_contracts_available`.
- `db.player_impact_pool(season: str | None) -> DataFrame`: all eligible rows for one season, or every season when None, ordered by impact desc.
- `db.player_impact_meta() -> dict`: the single meta row as a dict.
- `draft.BUDGET = 40`, `draft.ROSTER_SIZE = 8` (import from sim).
- `draft.validate_build(picks: DataFrame) -> list[str]`: human-readable problems. Possible messages:
  - "Pick 8 players (you have N)."
  - "Over budget: X of 40 credits."
  - "The same player can't appear twice." Same player_id in two different seasons is allowed in all-time mode; the same (player_id, season) twice is not.
  - An empty list means valid.
- `draft.snake_order(n_teams: int, rounds: int, user_slot: int) -> list[int]`: the team index for each pick. Snake order: round 1 is 0..n-1, round 2 is reversed, and so on.
- `draft.cpu_pick(available: DataFrame, roster: DataFrame, rng, usage_league_total=5.0) -> row index`:
  - Score = impact − 0.5 × max(0, projected roster usage including the candidate − usage_league_total × (len(roster)+1)/8) + rng.normal(0, 0.3).
  - Pick the argmax.
  - Must never return an index not in `available`.
- `draft.run_cpu_until_user(state, pool, rng)`: advances a draft state dict until it is the user's turn or the draft is done. State: `{"order": list[int], "pick_no": int, "rosters": {team_idx: [pool_index...]}, "taken": set}`.
- `draft.auto_rotation(roster_rows: DataFrame) -> DataFrame`: sorted by impact desc. The first 5 are starters.

**Tests (`tests/test_draft.py`):**
- `validate_build`: 7 picks → the count message; cost 41 → the budget message; a duplicate (player_id, season) → the duplicate message; a valid 8 → [].
- `snake_order(3, 2, user_slot=0)` == [0, 1, 2, 2, 1, 0].
- `cpu_pick`:
  - Over 200 random seeds it never returns a taken or missing index.
  - With noise disabled (rng normal returning 0 via a stub, or by passing `noise_sd=0`), it picks the max-impact row when the usage is fine.
  - Add a `noise_sd` param, default 0.3.
- A full draft with 6 teams × 8 rounds from a 100-row synthetic pool: every team ends with 8, no index is taken twice, and the result is deterministic for a fixed seed.
- `db.player_impact_available()` is False on `tmp_warehouse_without_marts`. With the new `warehouse_with_player_impact` fixture (a tiny tmp warehouse with both tables holding ~20 synthetic rows across 2 seasons), `player_impact_pool("2024-25")` returns only that season, ordered by impact desc, and `player_impact_pool(None)` returns all seasons.

**Commit:** these files, with the message "Add the team-builder pool, budget rules and CPU drafting".

---

### Task 4: Arcade "Build a team" tab (UI)

**Files:**
- Modify: `dashboard/views/arcade.py` (a third tab: "Build a team")
- Create: `tests/test_arcade_build.py`
- Modify: `dashboard/lib/glossary.py` (add terms: "Team rating", "Impact", "Projected record", "Title odds")

**Depends on:** Tasks 1-3 (`sim.py`, `draft.py`, the db functions, and the `player_impact` table in the local warehouse).

**UI spec:**
- The tab is `st.tabs(["Higher or Lower", "Mystery Player", "Build a team"])`.
- If `not db.player_impact_available()`: show `st.info("Team building needs a newer copy of the data - check back after the next refresh.")` and return.
- Controls row: a segmented control **Mode** (Build | Draft), a selectbox **Player pool** ("All-time" plus every season in the pool, newest first), and a "Start over" button. Changing mode or pool resets that mode's session state, after a confirm-free reset.
- Session state lives under keys prefixed `tb_`. Use only these keys.
- **Build mode:**
  - A search box plus a `st.dataframe` of the pool with single-row selection (`on_select="rerun", selection_mode="single-row"`). Columns: Player, Season, Team, GP, PTS, REB, AST, Impact (`glossary.marked("Impact")`) and Cost. Show the top 200 by impact after the search filter.
  - An "Add to team" button adds the selected row.
  - The roster shows as 8 slots in a card grid (`T.card_html`): 5 "Starter" slots, then 3 "Bench". Each filled slot shows the player, season, team (team color), impact and cost, with a remove (×) button.
  - The order within starters and bench is by impact, so no manual reordering.
  - The budget readout: a KPI showing "Credits used X / 40".
  - Validation messages come from `draft.validate_build`. Results are available only when the list is empty.
- **Draft mode:**
  - "Start draft" sets a random user slot (1-6) and runs the CPU until the user's turn.
  - A draft board (6 team columns × 8 rounds) shows picks as compact cards: player, season and impact.
  - On the user's turn, the same pool table and selection (excluding taken rows), with a "Draft player" button. CPU picks then run until the user's next turn.
  - When the draft is done, results are shown for the whole league.
- **Results (both modes):**
  - A team rating card row (`T.kpi`): Team rating (net, signed "+6.2", `help=glossary "Team rating"`), Projected record "57-25", Range "52-62 wins", and Best-record odds (Build) or Title odds (Draft) as "34%".
  - The projection uses `rng = np.random.default_rng(sim.roster_seed(ids))`, so it's stable.
  - Opponents:
    - Build plus a single season: that season's 30 real team net ratings, from `db.team_advanced(season)`.
    - Build plus all-time: 29 real team-seasons drawn with a fixed rng (seed 7) from all seasons' `mart_team_season.net_rating`. Add `db.all_team_net_ratings()` returning (season, team, net_rating) from 1985-86 on.
    - Draft: the 6 drafted teams via `sim.simulate_league`. Show a standings table (st.dataframe) of projected wins and title odds, with the user's team marked.
  - A "Simulate a season" button: a fresh `np.random.default_rng()`, run `simulate_season_once` or `simulate_league_once`.
    - Build: "62-20" plus a compact W/L strip of 82 small squares in an HTML div (green or red, reusing `.dot-w` and `.dot-l` styling), and the best and worst win streaks.
    - Draft: the season standings plus the playoff bracket as rows: "Round 1: You (1) 4-2 CPU 3 (4)". Name CPU teams "CPU 1".."CPU 5". Mark the champion with a chip.
- An explainer expander "How the simulation works": Impact, era adjustment, minutes split (32/16), usage overlap, game randomness (±12.7 points), and "same team → same projection; each simulated season differs".

**Tests (`tests/test_arcade_build.py`)**, using the `warehouse_with_player_impact` fixture from Task 3 extended with a tiny `main_marts.mart_team_season` (season, team_abbreviation, team_id, net_rating) for 2 seasons:
- With no player_impact table, the Build tab renders the info line and no exception.
- The tab renders with the table: mode Build, pool "2024-25", no exception.
- Simulate the session programmatically: put 8 rows into `st.session_state["tb_build_picks"]` (whatever structure you chose; document it in the module) and rerun. The results KPI row appears (a markdown containing "Projected record"), and running twice gives the identical projected record text, which is the determinism check.

**Commit:** `dashboard/views/arcade.py dashboard/lib/glossary.py dashboard/lib/db.py tests/test_arcade_build.py tests/conftest.py`, with the message "Add a Build a team mode to the Arcade: build or draft, then simulate".

---

### Task 5: Predictions page redesign

**Files:**
- Modify: `dashboard/views/predictions.py` (full rewrite of `render`)
- Modify: `dashboard/lib/db.py`, in the predictions section only: extend `upcoming_predictions`, and add `recent_settled_predictions` and `calibration_bins`
- Modify: `tests/test_predictions_page.py` (extend fixtures and tests)
- Modify: `dashboard/lib/glossary.py` (add "Win probability", "Predicted margin", "Calibration")

**Interfaces:**
- `db.upcoming_predictions(limit=30)` adds `s.tipoff_utc` to its select. It keeps returning the latest prediction per game.
- `db.recent_settled_predictions(n=20) -> DataFrame`. Columns: game_date, home, away, home_pts, away_pts, win_probability, predicted_margin, correct (bool). It uses the earliest prediction per game, the same rule as the track record, joined to results. Reuse the existing settled join that `prediction_track_record` uses; read that function first. Newest first.
- `db.calibration_bins(bins=10) -> DataFrame`. Columns: bin_mid, predicted_mean, actual_rate, n. Empty if fewer than 50 settled games.

**UI spec:**
- Header: "## Predictions" and a one-line caption explaining what the probability means.
- Upcoming, grouped by date:
  - Per date, a "#### Tue, Oct 20" heading, then cards in 3 columns, styled like the Games page `.bip-game`.
  - Each card has the tip-off time in US Eastern, formatted like "7:30 PM ET". Convert `tipoff_utc` with `zoneinfo.ZoneInfo("America/New_York")`; if `tipoff_utc` is null, show "TBD".
  - The away team line, then the home team line, each with `T.team_dot`.
  - A two-color probability bar: a single div with two inner divs whose widths are the away and home percentages, in each team's `T.team_color`, with the percentages as text labels beside it.
  - The verdict line: "BOS by 6 · 65%", with the favorite's abbreviation, the rounded margin and the favorite's probability.
- An expander "How these predictions are made": 3-4 plain sentences (Elo ratings, ridge margin to probability, form and rest not yet used for future games). Glossary tips on "Win probability" and "Predicted margin".
- "#### Track record":
  - Nothing settled: one `st.info` line, "The first predictions settle after opening night ({first upcoming date})." Use the first upcoming date if one exists, otherwise a generic line.
  - Otherwise: the existing KPI row (keep the glossary help), then the calibration chart if `calibration_bins` is non-empty.
    - A Plotly scatter+line of predicted_mean vs actual_rate, marker size by n, with a dashed y=x reference. Use the `viz._layout` styling: put the chart in `dashboard/lib/viz.py` as `viz.calibration_chart(df)` and follow that file's patterns.
    - Then a "Recent results" `st.dataframe`: Date, Matchup ("PHI @ NYK"), Pick ("NYK 68%"), Final ("NYK 112-104"), ✓/✗ via a Text column.
- No raw column names or raw decimals anywhere.

**Tests:**
- Extend `with_predictions_db`, or add a fixture, so the schedule has `tipoff_utc` and there is at least one settled and one upcoming game.
- The page renders in all three states: no table, upcoming only with 0 settled, and both.
- The markdown/html contains "ET" for a game with a tipoff and "TBD" for one without.
- The verdict format matches `r"[A-Z]{3} by \d+ · \d+%"`.
- No dataframe column header contains an underscore. Check `at.dataframe[i].value.columns`, after any renames.
- The "Recent results" grid shows ✓ or ✗.
- `db.calibration_bins` returns empty below 50 settled games (fixture). Add a unit test that builds a tmp warehouse with 60 synthetic settled games to check the bin math: n sums to 60, and actual_rate is in [0, 1].

**Commit:** `dashboard/views/predictions.py dashboard/lib/db.py dashboard/lib/viz.py dashboard/lib/glossary.py tests/test_predictions_page.py`, with the message "Rebuild the Predictions page: game cards, probability bars, calibration and recent results".

---

### Task 6: Integration, docs and verification (controller)

- Run the full pytest suite and the dbt tests.
- Run `python -m ml.player_impact` on the real warehouse.
- Run the CI simulation on fixtures. The Arcade build tab and the Predictions page must render on the fixture warehouse without player_impact; check the `player_impact` step in weekly_refresh doesn't break CI (CI doesn't run the refresh).
- Take Playwright screenshots of Predictions, Arcade build (both modes, results) and look at them.
- README: the Arcade and Predictions descriptions and the pipeline step list. The project layout gets `ml/player_impact.py`. DEPLOYMENT refresh-step list.
- Interview brief: add the player impact model (the team-aggregate vs individual plus-minus finding is a strong decision-log entry).
- Merge, push, run the refresh to publish player_impact, and tell the user to reboot.
