# Maintainability overhaul

Date: 2026-10-21. The user asked for this before any new features: every
practice a senior team at a top company would reject in review gets fixed.
Scope comes from three audits on 2026-10-21 (data access layer, tests and CI,
pipeline/ML/UI). Decisions made with the user, all the recommended options:

- **Python:** 3.12 everywhere (local, CI, Docker, devcontainer, Streamlit
  Cloud). The local `.venv` is rebuilt on 3.12, which also removes the dbt
  `mashumaro` workaround that 3.14 needed.
- **Play-by-play:** accumulates every game of the season. Today the file is
  overwritten each week with the 20 most recent games, so older games lose
  their charts.
- **Data location:** configurable. The warehouse and raw files move out of
  OneDrive, whose sync can lock files mid-write.

## Principles (binding on every task)

1. **Single source of truth.** Every number and every rule is defined in
   exactly one place: metrics in dbt marts, shared constants in `core/`,
   team-code facts in one seed file.
2. **Fail loudly, recover safely.** No swallowed errors, no half-written
   files, no half-built warehouse. Optional steps fail without blocking
   required ones.
3. **Expand, then contract.** Warehouse changes are additive until the code
   that reads them has shipped and the warehouse has been republished. The
   live site is never served code that needs data it doesn't have yet.
4. **The scheduled refresh keeps working at every merge to main.** It runs
   Tuesdays at 06:00 from the main checkout.
5. **Tests prove something in CI.** No silent skips; a test that needs the
   full warehouse says so with a marker, and CI fails on any other skip.

## What changes

### Phase 0: Tooling
- Python 3.12 declared in `pyproject.toml` and `.python-version`. CI, Docker
  and the devcontainer all use 3.12.
- Locked dependencies: `requirements.in` and `requirements-dev.in` hold the
  direct dependencies, and pip-tools compiles exact pins into
  `requirements.txt` and `requirements-dev.txt` (Streamlit Cloud reads the
  former).
- ruff (lint and format), mypy (gradual typing), and pre-commit, all
  configured in `pyproject.toml`. CI runs `ruff check`,
  `ruff format --check`, mypy, `dbt build`, and pytest with a skip guard and
  a timeout.

### Phase 1: Pipeline reliability
- A new top-level `core/` package: pure Python, no heavy dependencies,
  importable by ingestion, scripts, ml and the dashboard.
- `core/paths.py` resolves every path. `BIP_DATA_HOME` moves raw data and
  the warehouse; `BIP_WAREHOUSE` points at one warehouse file (used for the
  build copy and for tests). `.env` is loaded once there.
- Atomic parquet writes (temp file, then `os.replace`). A season counts as
  done only if its file actually opens.
- Retries only for transient errors (connection errors, timeouts, 5xx, 429
  honouring `Retry-After`, with jitter). One failing team no longer sinks a
  payroll season. `--force` refuses to replace a file with fewer rows.
- Play-by-play fetches only games not already stored (capped per run), and
  its failure is a warning, not a fatal error.
- The weekly refresh builds into a copy of the warehouse and swaps it in only
  when every required step passes. It gains per-step timeouts, checked git
  return codes, full per-step logs, a lock against overlapping runs, a
  version file written only after a successful upload, and `--no-publish`
  for dry runs.
- The predictions track record is also kept as a committed CSV, so it
  survives the loss of the warehouse file.

### Phase 2: dbt marts are the single source of truth
- `mart_player_season` adopts the dashboard's definitions, which are the
  more correct ones:
  - per-game averages skip games where that stat wasn't recorded;
  - TS% is withheld only when its own inputs (FGA, FTA, points) are missing.
  It gains every column the pages use, plus `age`.
- New models: `mart_player_team_season` (per-team stints and team paths),
  `mart_player_career`, `mart_league_shooting`.
- A `team_codes` seed is the one place for team-code facts (franchise, era
  name, conference, colours, Basketball-Reference code). dbt and Python
  (`core/teams.py`) both read it.
- dbt "known case" tests fail when their expected row is missing. A
  marts-not-empty test is added. The fixtures gain a 1985-96 season, a
  1996-97 advanced slice and the key payroll team-seasons, so CI exercises
  the same branches the full warehouse does.

### Phase 3: Data access layer
- `dashboard/lib/db.py` becomes the package `dashboard/lib/data/`, with one
  module per domain: core, seasons, players, teams, games, advanced,
  finances, predictions, arcade. It reads only marts. There is no
  string-surgery SQL, no standings fallback, and no dead code.
- Caches are keyed on the warehouse file's version, so a swapped warehouse
  is never served from stale caches. A single `objects_exist()` probe
  replaces six copies and catches only "object missing", never IO errors.
- Connection-per-query is kept on purpose: an open long-lived connection
  would lock the file on Windows and block the warehouse swap. The cost is a
  few milliseconds per cache miss.
- Tests point the data layer at a warehouse with `use_warehouse(path)`
  instead of monkeypatching module globals.

### Phase 4: Shared rules
- `core/constants.py` holds:
  - season boundaries (advanced stats from 1996-97, complete box scores from
    1985-86);
  - one measured game-margin standard deviation;
  - the Elo hyperparameters;
  - Arcade economy constants (budget, cost quantiles, max cost, the
    five-on-the-floor factor);
  - the play-by-play cap;
  - health-check thresholds aligned with the season rollover.
- Shared helpers: `core/text.py` (accent-insensitive search folding) and
  `core/fmt.py` (money, ordinal).
- `ml/predict.py`'s script body moves into testable functions, and the
  played-games query is shared.

### Phase 5: UI
- `dashboard/views/arcade.py` becomes the package `views/arcade/`
  (Higher or Lower, Mystery Player, Build a team).
- Long page functions are split into named sections.
- Card builders move from one view into another into `lib/cards.py`.
- Hard-coded colours become theme tokens via `T.rgba()`.
- Session-state keys become named constants.

### Phase 6: Docs
- README, DEPLOYMENT and a new CONTRIBUTING.
- New ADRs: tooling and locked dependencies; marts as the single source of
  truth; atomic writes and the warehouse swap; the data access layer and
  caching; the shared `core/` package.
- The architecture diagram and the known-limitations ADR are updated.

## Visible changes on the site

- Older games keep their game-flow and shot charts.
- Neutral-site games get the same home/away label on the Games page and in
  predictions.
- TS% shows on the Advanced page for old player-seasons where only unrelated
  team columns were missing.
- A few pre-1985 per-game averages change slightly, now that unrecorded
  games are no longer counted as zeros.
- FG% and 3P% for some 1979-80 to 1985-86 player-seasons (and that era's
  league benchmarks) are corrected: they now count only games where both
  makes and attempts were recorded, so no percentage can exceed 100.

## Rollout

Work happens in a worktree on branch `maintainability`, outside OneDrive.
Each phase is merged to main once green.

- **After Phase 0:** the main checkout's `.venv` is rebuilt on 3.12 and the
  refresh is dry-run with `--no-publish` once that exists.
- **After Phase 1:** data moves to `C:\Users\haiaj\bip-data` (set in `.env`).
- **After Phase 2:** the warehouse is republished before Phase 3's readers
  merge.
- **Before Tuesday 2026-10-27 06:00:** a full dry run on main.
