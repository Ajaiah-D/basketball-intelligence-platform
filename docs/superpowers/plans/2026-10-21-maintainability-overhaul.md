# Maintainability Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make the codebase something a senior team would approve: one Python
version, locked dependencies, lint/format/types in CI, a reliable pipeline,
dbt marts as the single source of truth, a domain-split data layer, shared
constants, smaller UI modules, and tests that prove something in CI.

**Architecture:** see `docs/superpowers/specs/2026-10-21-maintainability-overhaul-design.md`.
A new pure-Python `core/` package (paths, io, constants, text, fmt, teams) is
shared by ingestion, scripts, ml and the dashboard. `dashboard/lib/db.py`
becomes `dashboard/lib/data/`.

**Tech stack:** Python 3.12, pandas, DuckDB, dbt-duckdb, Streamlit, plotly,
scikit-learn (dev/ML only), pytest, ruff, mypy, pip-tools, pre-commit.

## Global Constraints

- Work only in the worktree `C:\Users\haiaj\Code\worktrees\bip-maintainability`
  on branch `maintainability`. Use its interpreter
  `.venv\Scripts\python.exe` (Python 3.12). Never push, never touch the main
  checkout in OneDrive. Commit on the branch when your task is green.
- Commit messages: human style, imperative subject under ~72 chars, a short
  body explaining why. **No `Co-Authored-By` or any AI attribution
  trailer.** No emoji.
- Code style: match the surrounding code. Comments explain *why*, as the
  existing ones do; don't narrate the obvious. Docstrings on public
  functions. No new dependencies beyond those named in this plan.
- The dashboard must never import `ml` or `scripts` (scikit-learn/scipy are
  dev-only and absent on the deployed app). `core/` imports only the
  standard library plus `python-dotenv` (and pandas/pyarrow only in
  `core/io.py`).
- **Expand then contract:** warehouse changes (dbt models/columns) are
  additive. Never drop or rename a column/table that code on `main` reads.
- The weekly refresh (`scripts/weekly_refresh.py`) must keep working after
  every task.
- No user-visible change beyond those listed in the spec's "Visible changes
  on the site".
- Every task ends green:
  - `.venv\Scripts\python.exe -m pytest -q` (full suite, local real
    warehouse);
  - from `dbt/basketball_intelligence`,
    `..\..\.venv\Scripts\dbt.exe build --profiles-dir .` when dbt files
    changed;
  - once Task 3 has landed, `ruff check .`, `ruff format --check .` and
    `mypy`.
- Shell: Windows. Git Bash and PowerShell are both available; in Git Bash
  set `MSYS_NO_PATHCONV=1` for URL-like args.

---

### Task 1: Python 3.12 and locked dependencies

**Files:** create `pyproject.toml`, `.python-version`, `requirements.in`,
`requirements-dev.in`; regenerate `requirements.txt`,
`requirements-dev.txt`; modify `.devcontainer/devcontainer.json`,
`.github/workflows/tests.yml`, `Dockerfile` (verify only).

- `.python-version` contains `3.12`.
- `pyproject.toml`, minimal for now (later tasks add tool sections):
  - `[project]` with name `basketball-intelligence-platform`, version
    `0.1.0`, `requires-python = ">=3.12,<3.13"`.
  - No build backend: it is not an installable package.
- `requirements.in` lists the current direct runtime dependencies,
  unpinned: `nba_api`, `pandas`, `duckdb`, `dbt-duckdb`, `streamlit`,
  `plotly`, `python-dotenv`, `requests`, `tzdata`.
  - Keep the tzdata comment.
  - Drop the Python 3.14 `mashumaro` note: on 3.12 dbt imports fine.
- `requirements-dev.in`:
  - `-c requirements.txt` as its first line;
  - then `pytest`, `scikit-learn`, `scipy`, `pyarrow`, `pip-tools`, `ruff`,
    `mypy`, `pre-commit`, `pandas-stubs`, `types-requests`.
- Compile with pip-tools on Python 3.12 (install `pip-tools` into the venv
  first):
  - `pip-compile --strip-extras --output-file requirements.txt requirements.in`
  - `pip-compile --strip-extras --output-file requirements-dev.txt requirements-dev.in`
  - Each compiled file keeps pip-tools' header, so the regeneration command
    is visible.
  - Add a one-line comment at the top of each `.in` file saying how to
    recompile.
- Reinstall the venv from the compiled files
  (`pip-sync requirements.txt requirements-dev.txt`). The full pytest suite
  must pass.
- devcontainer image → `mcr.microsoft.com/devcontainers/python:1-3.12-bookworm`.
- CI: keep `python-version: "3.12"`. Install with
  `pip install -r requirements.txt -r requirements-dev.txt`. Set the pip
  cache key to the compiled files via
  `cache-dependency-path: requirements*.txt`.
- Dockerfile already uses `python:3.12-slim`. Confirm it installs only
  `requirements.txt`.
- Acceptance:
  - `pip check` is clean;
  - pytest is green;
  - `dbt --version` runs without the mashumaro workaround.
- Commit: "Pin Python 3.12 and lock dependencies with pip-tools".

### Task 2: ruff lint and format

**Files:** `pyproject.toml` (add `[tool.ruff]`), every `.py` file.

- `[tool.ruff]`:
  - `target-version = "py312"`, `line-length = 100`;
  - `extend-exclude` covering `dbt/**/target`, `.venv` and `.superpowers`.
- `[tool.ruff.lint]`:
  - `select = ["E", "F", "W", "I", "B", "UP", "SIM", "RUF", "PTH", "N", "C4"]`;
  - `ignore = ["RUF001", "RUF002", "RUF003", "E501"]`. The RUF00x ignores are
    because the code intentionally uses `→`, `ⓘ`, `·` and accented names;
    the formatter handles line length.
- `[tool.ruff.lint.per-file-ignores]`:
  - `"tests/**" = ["N802", "PTH"]`;
  - `"dashboard/app.py" = ["E402"]`, because `sys.path` must be set before
    the imports.
- `[tool.ruff.format]`: `quote-style = "double"`.
- Two commits:
  1. `ruff format .` only. Commit "Format the codebase with ruff". It must
     be a pure formatting change: run the tests after.
  2. `ruff check . --fix`, then fix the remaining findings by hand. Prefer
     real fixes over `noqa`. Each `noqa` that stays needs a short reason
     comment on the same line.
     - Pay attention to `B` (bugbear) findings such as mutable defaults and
       loop-variable capture in lambdas (`views/games.py` uses
       `lambda v: "hi" if v == top`: check it's safe).
     - Commit "Fix ruff lint findings".
- Acceptance: `ruff check .` and `ruff format --check .` are clean, and
  pytest is green.

### Task 3: mypy, pre-commit, pytest markers and a stricter CI

**Files:**
- `pyproject.toml`: add `[tool.mypy]` and `[tool.pytest.ini_options]`.
- `.pre-commit-config.yaml`, `.github/workflows/tests.yml`,
  `tests/conftest.py`, and whichever test files need markers.

- `[tool.mypy]`:
  - `python_version = "3.12"`, `files = ["core", "dashboard", "ingestion", "ml", "scripts"]`;
  - `ignore_missing_imports = true`, `check_untyped_defs = true`;
  - `warn_unused_ignores = true`, `warn_redundant_casts = true`,
    `no_implicit_optional = true`.
  - `core/` does not exist yet. Write the config so it's included once
    created; if mypy errors on a missing path, list only the existing
    packages and add a TODO-free note in Task 4's file list to append it.
  - Fix the errors mypy reports, with real type fixes. Narrowly scoped
    `# type: ignore[code]` is allowed only with a reason.
  - Do not add annotations wholesale; this is gradual typing.
- `[tool.pytest.ini_options]`:
  - `testpaths = ["tests"]`;
  - `markers = ["full_warehouse: needs the full local warehouse (all seasons); deselected in CI"]`;
  - `addopts = "-ra"`.
- Mark as `full_warehouse` the tests that only run on the full warehouse:
  `tests/test_player_impact.py`'s `built`-fixture tests (lines ~210-260).
  Read each test that can `pytest.skip`. If its skip condition holds on the
  CI fixtures (seasons 1979-80, 1984-85, 2024-25 for game logs; 2024-25
  advanced; 1984-85 and 2024-25 payroll), mark it `full_warehouse`.
  Otherwise leave it.
- Skip guard in `tests/conftest.py`:
  - When `os.environ.get("CI")` is set, a `pytest_terminal_summary` or
    `pytest_sessionfinish` hook fails the session (exit status 1, with a
    clear message) if any test was skipped.
  - In CI the run uses `-m "not full_warehouse"`, so marked tests are
    deselected, not skipped.
  - Locally, skips are allowed.
- `.pre-commit-config.yaml`:
  - ruff (`ruff` with `--fix`, then `ruff-format`) and mypy, as local hooks
    using the venv (`language: system`, `entry: .venv/Scripts/...` won't
    work cross-platform, so use `language: system` with `entry: ruff` /
    `entry: mypy` and `pass_filenames: false` for mypy).
  - Plus `trailing-whitespace`, `end-of-file-fixer` and `check-yaml` from
    `pre-commit/pre-commit-hooks`, pinned to a release tag.
- CI workflow:
  - `timeout-minutes: 30` on the job.
  - A `lint` step before tests: `ruff check .`, `ruff format --check .`,
    `mypy`.
  - Replace the separate seed/run/test steps with `dbt build --profiles-dir .`.
  - pytest becomes `pytest -m "not full_warehouse"`.
- Acceptance:
  - locally, `pre-commit run --all-files` passes;
  - `mypy` is clean;
  - `pytest` is green;
  - `CI=1 pytest -m "not full_warehouse"` against a fixture-built warehouse
    is green with no skips. To build one: copy the repo's `data/fixtures/*`
    into a temp `data/raw`, run `scripts/load_to_duckdb.py` and `dbt build`
    against a temp warehouse path, as the CI workflow does. Before Task 4
    exists you may do this in a scratch copy of the worktree.
- Commit: "Add mypy, pre-commit and a stricter CI".

### Task 4: core package and one source for paths

**Files:**
- Create `core/__init__.py`, `core/paths.py`, `tests/test_core_paths.py`.
- Modify every hard-coded warehouse/raw path:
  - `scripts/load_to_duckdb.py`, `scripts/season_teams.py`,
    `scripts/write_metadata.py`, `scripts/health_check.py`,
    `scripts/weekly_refresh.py`;
  - `ml/predict.py`, `ml/evaluate.py`, `ml/player_impact.py`;
  - `ingestion/nba_ingest.py`, `ingestion/team_payroll_ingest.py`,
    `scripts/backfill_team_payroll.py`;
  - `dashboard/lib/db.py`, `dashboard/app.py`;
  - `dbt/basketball_intelligence/profiles.yml`.
- Add `core` to mypy `files` and to the Dockerfile `COPY` list (the
  dashboard will import it).

`core/paths.py` API:

```python
PROJECT_ROOT: Path            # repo root
def data_home() -> Path | None: ...      # BIP_DATA_HOME, or None when unset
def raw_dir() -> Path:        # BIP_DATA_HOME/raw, else PROJECT_ROOT/data/raw
def warehouse_path() -> Path: # BIP_WAREHOUSE, else BIP_DATA_HOME/warehouse/basketball.duckdb,
                              # else PROJECT_ROOT/warehouse/basketball.duckdb
def warehouse_version_path() -> Path:  # warehouse_path().with_suffix(".version")
def release_version_path() -> Path:    # warehouse_path().parent / "version.txt"
def fixtures_dir() -> Path:   # PROJECT_ROOT/data/fixtures
def logs_dir() -> Path:       # PROJECT_ROOT/logs (stays in the repo: run logs are committed)
```

- `.env` is loaded once, on import of `core.paths`, with
  `load_dotenv(PROJECT_ROOT / ".env", override=False)`. Real environment
  variables win.
- Functions, not module constants, so tests can set env vars with
  `monkeypatch.setenv`.
- dbt profile:
  `path: "{{ env_var('BIP_WAREHOUSE', '../../warehouse/basketball.duckdb') }}"`.
  `weekly_refresh.py` must pass `BIP_WAREHOUSE=<resolved warehouse_path()>`
  in the environment of every child process, so dbt and the scripts agree
  even when only `BIP_DATA_HOME` is set.
- `data/last_updated.json` and `logs/` stay in the repo (they are committed
  by the refresh).
- Tests cover:
  - the defaults with no env;
  - `BIP_DATA_HOME` moving raw and the warehouse;
  - `BIP_WAREHOUSE` overriding the file only;
  - the version paths.
- Acceptance:
  - `grep -rn "basketball.duckdb\|data\" / \"raw\|\"data\" / \"raw\"" --include=*.py`
    finds only `core/paths.py` and tests;
  - pytest is green;
  - a dbt build works with `BIP_WAREHOUSE` pointing at a copied file.
- Commit: "Resolve every data path in core.paths".

### Task 5: Ingestion reliability

**Files:**
- Create `core/io.py`, `tests/test_core_io.py`.
- Modify `ingestion/nba_ingest.py`, `ingestion/team_payroll_ingest.py`,
  `tests/test_nba_ingest.py`, `tests/test_team_payroll_ingest.py`.

`core/io.py`:

```python
def atomic_write_parquet(df: pd.DataFrame, path: Path) -> None:
    """Write to <path>.tmp in the same directory, fsync, then os.replace onto path."""
def is_valid_parquet(path: Path) -> bool:
    """True when the file exists and its footer reads (pyarrow.parquet.read_metadata)."""
def parquet_row_count(path: Path) -> int | None:
    """Row count from the footer, or None when missing/unreadable."""
```

- Every parquet write in both ingesters goes through
  `atomic_write_parquet`. "Season done" checks use `is_valid_parquet`, so a
  corrupt file is refetched, with a warning logged.
- Retry policy, in one place per ingester (a shared `core.io`
  `retry_transient` helper is fine if it stays dependency-light):
  - Retry: `requests.ConnectionError`, `requests.Timeout`, HTTP 5xx, and
    HTTP 429. For 429, honour `Retry-After` (seconds), else back off
    60/120/240 s for Basketball-Reference.
  - Exponential backoff with jitter. Keep the existing attempt counts.
  - Do not retry anything else: `TypeError`, `KeyError`, `ValueError`, HTTP
    404, empty results.
  - `nba_api` wraps errors in its own way: inspect what `call_endpoint`
    sees and retry only the transient ones.
  - Never `except Exception` around a retry.
- Payroll: process teams one at a time.
  - A team that fails (after retries) is logged and listed in a summary.
    The season's file is written with the teams that succeeded.
  - If any team failed, the script exits non-zero after writing. The
    refresh already treats payroll as non-fatal.
  - A 404 for a team is recorded as "no table" (an empty row set for that
    team), not retried.
- `--force` guard: when replacing an existing current-season file (game
  logs, player/team advanced, schedule, payroll), refuse to write if the
  new row count is below the existing file's count. Log an error, keep the
  old file and exit non-zero. Override with an explicit
  `--allow-shrink` flag.
- Replace any `print` in these ingesters with the module logger.
- Tests (no network; mock the endpoint/requests):
  - atomic write leaves no `.tmp` and survives a simulated crash (the
    original stays intact);
  - an invalid file is treated as not done;
  - 429 with `Retry-After` is honoured (patch `time.sleep`);
  - a 404 is not retried;
  - `TypeError` is not retried;
  - one failing team doesn't stop the others;
  - the shrink guard.
- Commit: "Make ingestion writes atomic and retries transient-only".

### Task 6: Play-by-play accumulates and can't block the refresh

**Files:** `ingestion/nba_ingest.py`, `scripts/weekly_refresh.py`,
`tests/test_nba_ingest.py`; `core/constants.py` (create it with just
`PBP_MAX_NEW_GAMES_PER_RUN = 120`; Task 14 adds the rest).

- Play-by-play for the latest season is incremental:
  1. read the existing `play_by_play/<season>.parquet` if valid;
  2. collect the stored `gameId`s;
  3. take the season's played game ids newest first, minus the stored ones,
     capped at `PBP_MAX_NEW_GAMES_PER_RUN`;
  4. fetch only those;
  5. concat with the existing rows, de-duplicate on (`gameId`, `actionNumber`)
     or the existing unique action key (check `stg_play_by_play.sql` for the
     grain), and write atomically.
- Games that fail are simply fetched next run, since they're still missing.
- The play-by-play step runs **after** game logs, advanced, schedule,
  players and teams have been written. If every play-by-play fetch fails,
  log a warning and continue: no exception, exit 0, and core data intact.
- `--pbp-games N` keeps meaning "at most N new games this run". The
  refresh passes `PBP_MAX_NEW_GAMES_PER_RUN`, imported, not a literal.
- Keep the existing rule that no games played yet means skip.
- Tests:
  - only missing games are fetched;
  - existing rows survive;
  - de-duplication works;
  - the cap is respected;
  - all-fail doesn't raise, and the core files are written first.
- Commit: "Accumulate play-by-play and make it non-fatal".

### Task 7: A safe, observable weekly refresh

**Files:** `scripts/weekly_refresh.py`, `scripts/load_to_duckdb.py`,
`.gitignore` (add `logs/runs/`), `tests/test_weekly_refresh.py`.

- Build in a copy:
  - At start, copy the current warehouse (if it exists) to
    `<warehouse>.next.duckdb` (`.next` before the suffix).
  - Every child step runs with `BIP_WAREHOUSE` set to the copy.
  - Only when every required step passes: close everything, then
    `os.replace` the copy onto the real path, and move any `.wal` files
    aside or remove them safely.
  - On failure, delete the copy and leave the real warehouse untouched.
  - If the replace itself fails (for example a running local dashboard
    holds the file on Windows), record a clear error and do not publish.
- `load_to_duckdb.py`: wrap all `CREATE OR REPLACE` statements in one
  transaction (`BEGIN`/`COMMIT`, `ROLLBACK` on error), and close the
  connection in `finally`.
- Steps:
  - `subprocess.run(..., timeout=STEP_TIMEOUT_SECONDS[name])`, with
    defaults: ingest 3600, payroll 1800, dbt steps 1800, others 900. Catch
    `TimeoutExpired` as a failed step.
  - Keep the full stdout+stderr of every step in
    `logs/runs/<run_at>/<step>.log` (gitignored, `run_at` filesystem-safe),
    and put that path in the JSONL entry.
  - The JSONL `error` field keeps a tail, but take it from stdout+stderr
    combined, so dbt's stdout errors aren't lost.
- dbt: run `dbt build` once instead of separate seed/run/test steps, so a
  failing model blocks its own tests. Keep one step name, `dbt_build`, and
  make sure `health_check.py` and any consumers of step names still work
  (grep for `dbt_seed`, `dbt_run` and `dbt_test`).
- Wrap `main()` in `try/finally` so the JSONL line is always written.
- Publishing:
  - write `version.txt` (path from `core.paths.release_version_path()`)
    only after the upload succeeds;
  - if the upload fails, restore the previous version file.
- Check the return codes of `git add`, `git commit` and `git push`, and
  record a `git_push` step entry (with ok/error) in the run, before writing
  the log. The log for this run is written before the commit, so the push
  result of this run is printed and appended as a second JSONL line
  `{"run_at":..., "step":"git_push", ...}`. Keep it simple and documented.
- Lock: create `logs/refresh.lock` with `os.open(O_CREAT|O_EXCL)`, holding
  the pid and start time. If it already exists and is younger than 6 hours,
  exit 2 with a message; if older, take it over with a warning. Remove it
  in `finally`.
- `--no-publish` flag: run everything except the release upload, the swap
  and the git commit/push. It builds the copy, runs every step, reports,
  then deletes the copy. This is the dry run used before Tuesday's
  scheduled run.
- `print` becomes `logging` with timestamps.
- Tests (subprocess mocked):
  - the copy is swapped only on success;
  - a failure leaves the original untouched and deletes the copy;
  - a timeout is recorded as a failure;
  - the version file is written only after the upload;
  - the lock prevents overlap;
  - `--no-publish` touches nothing;
  - git push failure is recorded;
  - the existing tests are updated for `dbt_build`.
- Commit: "Build the warehouse in a copy and harden the weekly refresh".

### Task 8: A durable predictions history and a testable predict

**Files:** `ml/predict.py`, `ml/evaluate.py`, `scripts/load_to_duckdb.py`,
`scripts/weekly_refresh.py`, `data/predictions/history.csv` (new,
committed), `tests/test_predict.py` (new or extend existing ml tests).

- Read how `ml/predict.py` stores predictions today: the warehouse table
  `predictions`, append-only, and `ml/evaluate.py` scores it.
- The committed `data/predictions/history.csv` becomes the source of truth
  for issued predictions.
  - Columns are exactly the table's columns. Rows are append-only, sorted by
    creation time then game_id.
  - Never rewrite or reorder past rows: git diffs stay append-only.
- `ml/predict.py` appends new predictions to the CSV and to the warehouse
  table in the same run.
- `load_to_duckdb.py` (re)builds the warehouse `predictions` table from the
  CSV when the CSV exists, keeping the same table name and schema the
  dashboard reads.
- One-time migration: export the current warehouse `predictions` rows (in
  the worktree's copied warehouse) into the CSV, so history starts complete.
  Do this as part of this task and commit the CSV.
- The refresh's git add includes `data/predictions/history.csv`.
- Move `ml/predict.py`'s `if __name__ == "__main__":` body into
  `main()` → `fit_and_predict(con) -> pd.DataFrame` plus
  `append_history(df, path)`. Unit test `append_history`:
  - append-only;
  - no duplicate `game_id` per model version (check the table's natural
    key);
  - stable order.
- `ml/*` `print` calls become `logging`.
- Commit: "Keep the predictions history as a committed CSV".

### Task 9: One team-codes seed

**Files:**
- Create `dbt/basketball_intelligence/seeds/team_codes.csv`,
  `core/teams.py`, `tests/test_core_teams.py`.
- Modify `dbt/.../marts/mart_team_standings.sql`, the seeds `.yml` (add
  tests), `dashboard/lib/franchises.py`, `dashboard/lib/theme.py`,
  `dashboard/lib/db.py` (`EAST`/`WEST`/`conference`),
  `ingestion/team_payroll_ingest.py` (code maps).

- Today team-code facts live in 5 places:
  - `db.py` EAST/WEST (~lines 36-44);
  - `franchises.py` ERAS;
  - `theme.py` historical team colours (~43-58);
  - `team_payroll_ingest.py` code maps (~69-94);
  - the conference lists in `mart_team_standings.sql` (~72-80).
- Reconcile them into one CSV, one row per (team code, era).
  - Columns: `team_code, first_season, last_season, franchise_id, era_name,
    conference, color, bbref_code`.
  - `first_season`/`last_season` are "YYYY-YY" strings, empty meaning
    open-ended.
  - Every code that appears in the warehouse's team game logs or payroll
    must be covered.
  - Where sources disagree, read the comments and tests to decide, and
    note the decision in the CSV-adjacent YAML description.
- `core/teams.py` reads the CSV with the `csv` module. It caches with
  `functools.cache` and exposes:
  - `conference(code, season) -> str` (raises `KeyError` on an unknown code,
    never defaulting to West);
  - `franchise_of(code, season)`, `era_name(...)`, `color(code)`,
    `bbref_code(code, season)`, as needed by the current call sites.
  - Keep the current public functions in `franchises.py`/`theme.py` as thin
    wrappers, or update their callers. Prefer updating callers when there
    are few.
- dbt: `mart_team_standings` takes `conference` from the seed via a join on
  code and season range, and stays null for an unknown code, so the
  existing not_null test fails loudly. Add seed tests: `not_null` on
  `team_code`, `conference`, `franchise_id`; a uniqueness test on
  (team_code, first_season).
- Behaviour must not change.
  - Snapshot the current outputs first: every team's conference per season
    from `mart_team_standings`, `franchises.annotate()` on the payroll
    history, and `theme.team_color` for every code.
  - Assert they're identical after (a one-off script is fine; keep a
    compact regression test in `tests/test_core_teams.py`).
- Commit: "Keep team codes, eras, conferences and colours in one seed".

### Task 10: dbt marts become the single source of player stats

**Files:**
- Modify `dbt/.../marts/mart_player_season.sql` and `_marts_models.yml`.
- Create `dbt/.../marts/mart_player_team_season.sql`,
  `mart_player_career.sql`, `mart_league_shooting.sql`, and a singular test
  `assert_player_season_matches_game_logs.sql`.
- Also `tests/test_db_metrics.py`.

**Additive only.** Existing columns keep their names. Where a definition
changes (below), the column keeps its name and gets the corrected
definition.

- Reference definitions: the dashboard's `_PLAYER_SEASON_SQL` in
  `dashboard/lib/db.py` (~lines 85-121), `_PLAYER_CAREER_SQL` (~244-284),
  `player_season_breakdown` (~293-326), `player_team_paths` (~198),
  `league_shooting_averages` (~339), and `_ARCADE_AGES_SQL` (~882).
- `mart_player_season` (grain: season × player):
  - **Per-game averages** use `avg(stat)` (non-null games only): points,
    rebounds, assists, steals, blocks, threes made, FGA, 3PA, FTA,
    plus/minus, minutes.
    - Existing `points_per_game`/`minutes_per_game` switch to this
      definition.
    - New columns: `rebounds_per_game`, `assists_per_game`,
      `steals_per_game`, `blocks_per_game`, `threes_made_per_game`,
      `fga_per_game`, `three_pa_per_game`, `fta_per_game`,
      `plus_minus_per_game`, rounded to 1 decimal as the dashboard does.
  - **Totals:** `fga_total`, `tpa_total`, `fta_total` (int); keep the
    existing totals.
  - **Percentages:** `fg_pct`, `fg3_pct`, `ft_pct` (made/attempted × 100,
    1 decimal, null when attempts are 0), and `assist_to_turnover`.
  - **`true_shooting_pct`**: null only when any of the player's games that
    season has a null FGA, FTA or points; otherwise
    `points / (2 × (FGA + 0.44 × FTA)) × 100`. That is the dashboard rule.
    The other advanced metrics keep their `box_score_complete` gating.
  - **`team`** (last team by game date) and **`team_path`** (`'A → B'`
    ordered by first game with that team, a single code when one team).
  - **`age`**: the NBA's age from `stg_player_advanced` when present.
    Otherwise counted back or forward from the player's earliest season
    with a known age: `age0 + (start_year(season) − start_year(anchor))`,
    floored to int. Null when the player has no known age.
  - Verify the row set equals one row per (season, player) in
    `stg_player_game_logs`. The singular test
    `assert_player_season_matches_game_logs` fails on any season-player
    missing from either side, or any `games_played` mismatch.
- `mart_player_team_season` (grain: season × player × team): the same stat
  columns computed over that stint's games, plus `first_game`. This is
  what the Teams roster needs.
- `mart_player_career` (grain: player):
  - `seasons`, `first_season`, `last_season`, last `team`, `games_played`,
    `pts_total`;
  - per-game averages and percentages over the whole career, with the same
    definitions;
  - TS% with the same null rule over the career;
  - `career_high` (max points in a game), `wins`, `shot_poss`. Match the
    dashboard's `player_career_stats` output columns semantically.
- `mart_league_shooting` (grain: season): volume-weighted FG%, 3P% and FT%,
  plus whatever `league_shooting_averages` returns, with `nullif` guards.
- `_marts_models.yml`:
  - describe every new model and column;
  - `not_null`/`unique` tests on the grains;
  - `accepted_range`-style checks where they exist in the project (match
    the existing style).
- Regression check: a test in `tests/test_db_metrics.py` (real warehouse,
  marked `full_warehouse` if it needs more than the fixtures) asserts that
  for every season the new mart columns equal the current dashboard
  queries' results:
  - exact equality on rounded values;
  - TS% equal, including nulls.
  This proves the switch in Task 12 changes nothing on the Players page.
  Document any intended difference (there should be none versus the
  dashboard; the differences versus the old mart are the point).
- Commit: "Make the player marts the single source of player stats".

### Task 11: dbt tests that can fail, and fixtures that exercise them

**Files:**
- dbt singular tests:
  - `assert_team_finances_known_tax_case.sql`
  - `assert_team_finances_flags_2023_24_taxpayers.sql`
  - `assert_team_finances_does_not_overflag.sql`
  - `assert_team_finances_reason_distinguishes_real_low_payroll.sql`
  - `assert_team_finances_flags_incomplete_payroll.sql`
  - `assert_no_future_data_in_features.sql`
  - new `assert_marts_not_empty.sql`
- `_marts_models.yml` (`not_null` on `mart_team_contracts` season,
  team_abbreviation, bbref_player_id).
- `data/fixtures/**` (new slices).
- Python tests: `tests/test_finances_page.py`, `tests/test_features.py`,
  `tests/test_sim.py`, `tests/test_draft.py`, `tests/test_arcade_cards.py`,
  `tests/test_season_teams.py`, `tests/test_franchises.py`.

- **Known-case pattern.** Rewrite each known-case test as an expected
  `values` CTE, `left join`ed to the mart, returning a row when the mart row
  is missing **or** wrong. A missing row must now fail.
- **`assert_marts_not_empty`:** every mart has more than 0 rows, and
  `mart_team_finances` has 30 teams for the newest payroll season present.
- **`assert_no_future_data_in_features`:**
  - sample deterministically (`using sample 500 rows (reservoir, 42)` or
    `repeatable(42)`, whichever DuckDB syntax the project's version
    supports);
  - add an arm that fails when the sample is empty.
- **Fixtures.** Slice from the local full data (`core.paths.raw_dir()`,
  the worktree copy) so CI exercises what it currently can't:
  - player and team game logs for one complete season in 1985-86..1995-96:
    use `1990-91`;
  - `player_advanced`/`team_advanced` for `1996-97`, so ages can be
    anchored for players who also appear in 1990-91;
  - payroll and payroll_players rows for exactly the team-seasons the
    known-case tests name: 2023-24 taxpayers, 2009-10 BOS, 1998-99 HOU,
    1988-89 MIA, and the incomplete-payroll rows. Only those team-seasons,
    to keep fixtures small. Check each test file for the exact keys.
  - Keep each new file under ~2 MB. Update `data/fixtures/README` if one
    exists, or add a short one listing what each slice is for.
- After adding fixtures, the CI-style build (fixtures → `load_to_duckdb` →
  `dbt build`) must pass, and every known-case test must really evaluate
  its rows. Prove it by temporarily breaking one expected value and seeing
  the test fail; revert that.
- Python test strengthening:
  - `test_finances_page`: assert the team's name or a payroll figure
    renders.
  - `test_features`: assert `margin`/`home_won` aren't in the feature frame
    columns.
  - `pytest.raises(..., match=...)` everywhere it lacks `match`.
  - `test_sim` line ~172: assert a real bound instead of `len > 1`.
  - `test_arcade_cards`: the ages-drift test asserts at least one player
    has 2+ seasons with a known age (it will, with the 1990-91 + 1996-97
    fixtures).
  - `test_season_teams`: remove the silent `if season in ...` branches.
    Assert on seasons the fixtures contain, or mark `full_warehouse`.
  - `test_franchises`: covered relocated eras must be asserted, not
    skipped.
- Acceptance: the CI-style run (`CI=1`, `-m "not full_warehouse"`) is green
  with zero skips; the local full run is green.
- Commit(s): "Make dbt known-case tests fail on missing rows",
  "Add fixture slices so CI exercises every branch".

### Task 12: Data layer package, part 1 (core, seasons, players, arcade)

**Files:**
- Create `dashboard/lib/data/__init__.py`, `data/core.py`,
  `data/seasons.py`, `data/players.py`, `data/arcade.py`.
- Modify the views `players.py`, `overview.py`, `arcade.py`, `advanced.py`
  (only the player/season calls).
- Modify tests: `tests/conftest.py`, `test_players_page.py`,
  `test_arcade_build.py`, `test_arcade_cards.py`, `test_db_metrics.py`,
  `test_draft.py`.
- `db.py` keeps working for the not-yet-moved domains (remove the moved
  functions from it).

`data/core.py`:

```python
def warehouse_path() -> Path            # core.paths.warehouse_path(), overridable by use_warehouse
def warehouse_version() -> int          # mtime_ns of the file, 0 when missing
def warehouse_exists() -> bool
def q(sql: str, params: tuple = ()) -> pd.DataFrame
    # runs on a fresh read-only connection; cached with st.cache_data(ttl=CACHE_TTL_SECONDS)
    # on (sql, params, warehouse_path, warehouse_version) so a swapped file never serves stale results
def objects_exist(*names: str) -> bool
    # True when every schema-qualified object exists (one information_schema query);
    # cached the same way; catches only duckdb.CatalogException-style "missing" cases,
    # lets IO errors raise
def clear_caches() -> None              # clears q/objects_exist caches
@contextmanager
def use_warehouse(path: Path)           # tests: point the data layer at a file, clear caches, restore after
CACHE_TTL_SECONDS = 600
```

- Keep connection-per-query and document why in the module docstring: a
  long-lived connection locks the file on Windows and blocks the
  refresh's swap; a fresh read-only DuckDB connection costs milliseconds.
- `data/seasons.py`: `seasons()`, `latest_season()`.
- `data/players.py`: the current public functions, same names and return
  columns, now selecting from the marts with aliases to the short names the
  views use (`ppg`, `rpg`, ...):
  - `player_season_stats`
  - `team_roster`
  - `player_team_paths` (or fold `team_path` into `player_season_stats` and
    drop `with_team_labels` from the views)
  - `player_career_stats`
  - `player_season_breakdown`
  - `player_game_log`
  - `league_shooting_averages`
  - `player_latest_seasons`: written plainly against
    `mart_player_season`, one query, final `ORDER BY` as documented.
    Accent folding uses `core.text.fold` if it exists by then, otherwise a
    local helper; Task 14 consolidates.
  - `qualification_threshold` moves to `dashboard/lib/stats.py` with
    `percentile_of`.
- `data/arcade.py`:
  - `arcade_pool` reads `mart_player_season` (with `age`), filtering
    `games_played >= 50 and points_per_game >= 14.0`;
  - `player_ages_available` goes away: `age` is a mart column now. Use
    `objects_exist` only for objects that may genuinely be missing.
  - `player_impact_available` → `objects_exist("main.player_impact",
    "main.player_impact_meta")`; then `player_impact_pool`,
    `player_impact_meta`, `all_team_net_ratings`. The `'1985-86'` literal
    becomes a named constant (Task 14 moves it to `core/constants.py`).
- No SQL is built by `.replace()`, `.format()` or concatenating SQL
  fragments. `f"{cols}"` with a fixed internal column list is acceptable
  only if documented; prefer writing it out.
- Tests:
  - Replace every `monkeypatch.setattr(db, "DB_PATH", ...)` and `db.q.clear()`
    for these domains with `use_warehouse(path)`. Update `conftest.py`
    fixtures to use it.
  - Views import `from dashboard.lib.data import players, seasons, arcade as arcade_data`
    (choose clear aliases).
  - The regression test from Task 10 now compares old versus new through
    the views' output columns where useful.
- Acceptance: pytest green (local full + CI-style), ruff, mypy; the Players,
  Overview, Advanced and Arcade pages render unchanged. Spot-check with
  AppTest:
  - Luka Dončić 2025-26: 33.5 PPG, 64 GP;
  - the search fallback still finds Michael Jordan 2002-03.
- Commit: "Start the data package: core, seasons, players, arcade".

### Task 13: Data layer package, part 2 (teams, games, advanced, finances, predictions); delete db.py

**Files:**
- Create `dashboard/lib/data/teams.py`, `games.py`, `advanced.py`,
  `finances.py`, `predictions.py`.
- Delete `dashboard/lib/db.py`.
- Modify every view and `dashboard/app.py`, `views/dev_lab.py`, and every
  test that imports `db`.

- `teams.py`:
  - `standings` reads only `mart_team_standings` (remove the staging
    fallback and its `conference()` default);
  - `team_game_log`;
  - `conference` comes from `core.teams`.
- `games.py`:
  - `games_list` reads `fct_team_game`, which fixes neutral-site home/away
    to match predictions;
  - `pbp_game_ids`, `game_pbp`, `game_box_score` (explicit columns, no
    `select *`).
- `advanced.py`:
  - `player_advanced`, `team_advanced`, `advanced_seasons`;
  - `marts_available` → `objects_exist(...)`.
  - `ADVANCED_METRICS` (UI metadata) moves to `dashboard/views/advanced.py`
    or `dashboard/lib/metrics.py`.
  - Delete the dead `player_advanced_career`.
- `finances.py`:
  - `team_finances_available`, `team_payroll_history` (filter in SQL by the
    franchise's codes for the era where possible; otherwise document why
    pandas), `salary_cap_history`, `team_contracts_available`,
    `team_contracts`.
- `predictions.py`:
  - `predictions_available` (schema-qualified `main.predictions`);
  - `upcoming_predictions`, `prediction_track_record`,
    `recent_settled_predictions`.
  - `calibration_bins` math moves to `dashboard/lib/stats.py`.
  - `_SETTLED_PREDICTIONS_SQL` must not drift from `ml/evaluate.py`. The
    dashboard can't import `ml`, so move the SQL into a dbt model
    `mart_settled_predictions` that both read. `ml/evaluate.py` may still
    compute its metrics in Python from that model. This is additive: a new
    model.
- `app.py` uses `data.core` (`warehouse_exists`, `clear_caches()` after a
  download, and path/version from `core.paths`).
- Magic numbers become named constants at the top of their module (e.g.
  `CALIBRATION_MIN_GAMES = 50`, the 0.5 probability threshold) unless Task
  14's `core/constants.py` is the right home.
- Acceptance:
  - `dashboard/lib/db.py` is gone;
  - `grep -rn "from dashboard.lib import.*\bdb\b\|lib\.db\|db\." dashboard tests`
    finds nothing stale;
  - every page renders in AppTest;
  - pytest (local + CI-style), ruff and mypy are green.
- Commit: "Finish the data package and remove db.py".

### Task 14: Shared constants and helpers in core

**Files:**
- Create or complete `core/constants.py`, plus `core/text.py`,
  `core/fmt.py` and tests.
- Modify:
  - `ml/elo.py`, `ml/train.py`, `ml/features.py`, `ml/predict.py`,
    `ml/evaluate.py`, `ml/player_impact.py`;
  - `dashboard/lib/sim.py`, `draft.py`, `payroll.py`, `team_metrics.py`;
  - `views/players.py`, `views/arcade.py`;
  - `ingestion/nba_ingest.py`, `scripts/health_check.py`.

- `core/constants.py`:
  - `ADVANCED_STATS_FIRST_SEASON = "1996-97"` and
    `COMPLETE_BOX_SCORE_FIRST_SEASON = "1985-86"`;
  - `ELO_K`, `ELO_HOME_ADVANTAGE`, `ELO_SEASON_CARRY` (the current
    20/100/0.75);
  - `GAME_MARGIN_SD`: one value. Today `ml/train.py MARGIN_SD = 13.5` (its
    comment says the log-loss optimum is 11.24) and `sim.py GAME_SD = 12.7`.
    - Measure on the warehouse the residual SD of actual margin around the
      model's predicted margin on the holdout, and the log-loss-optimal SD,
      with a short script.
    - Pick one value and document the measurement in the constant's
      comment.
    - If the two serve genuinely different purposes, keep two clearly
      named constants with a comment explaining why. Don't merge numbers
      that mean different things.
    - Report what you found.
  - `HOME_EDGE_POINTS = 2.5`;
  - Arcade economy: `ARCADE_BUDGET = 36`, `COST_QUANTILES` (moved from
    `ml/player_impact.py`), `MAX_COST = len(COST_QUANTILES) + 1`,
    `PLAYERS_ON_FLOOR = 5`;
  - `PBP_MAX_NEW_GAMES_PER_RUN` (already there);
  - health-check thresholds, as named constants aligned with the October 1
    rollover.
- Elo defaults come from the constants in both `compute_elo` and
  `current_ratings`. A test asserts their defaults are identical.
- `core/text.py`: `fold(text) -> str`, replacing the 3 copies (arcade,
  players, data.players).
- `core/fmt.py`: `money`, `ordinal`, moved from `dashboard/lib/payroll.py`.
  Update `team_metrics.py` and the callers.
- `ml/features.py`: `load_played_games(con)`, used by both `features` and
  `predict` (removes the duplicated query and the 0-0 no-contest filter).
- `ml/player_impact.py`: read `usage_league_total` from its own fit/meta
  rather than a duplicated 5.0 where applicable (see the audit: the factor
  appears in `sim.py:54,62` and `player_impact.py:57,203`).
- Behaviour unchanged, except an intentional, documented margin-SD
  decision. Note that changing the SD changes predicted probabilities: if
  a change is warranted, state it clearly in the commit and in your report.
- Commit: "Move shared rules and helpers into core".

### Task 15: Split the Arcade into a package

**Files:**
- Create `dashboard/views/arcade/__init__.py` (the `render()` with tabs),
  `higher_lower.py`, `mystery.py`, `team_builder/__init__.py`,
  `team_builder/build.py`, `team_builder/draft.py`,
  `team_builder/results.py`, `team_builder/state.py` (session-state keys as
  named constants plus reset helpers), `cards.py` (`player_card`,
  `stat_html`).
- Delete `dashboard/views/arcade.py`.
- Update `dashboard/app.py` (page import), the tests that import
  `dashboard.views.arcade` (keep a stable import path; tests call
  `arcade.render_build_team`, `arcade.player_card`, `arcade.my_clues`,
  `arcade._rating`, `arcade._tb_*`, etc.), and the AppTest scripts.

- Pure move-and-organize: no behaviour change.
  - Session-state keys become constants in `state.py`. The string values
    stay identical, so tests that set `tb_*` keys keep working.
  - Tests may be updated to import from the new modules. Callbacks keep
    their names unless renaming is clearly better; then update the tests.
- Each module gets a docstring saying what it owns.
- Acceptance: all Arcade tests green unchanged in behaviour; files are each
  under ~350 lines; ruff and mypy clean.
- Commit: "Split the Arcade view into one module per game".

### Task 16: Tidy the other views and the theme

**Files:** `dashboard/views/players.py`, `advanced.py`, `teams.py`,
`finances.py`, `games.py`, `overview.py`; `dashboard/lib/theme.py`,
`viz.py`, `media.py`; `dashboard/app.py`; new `dashboard/lib/cards.py`.

- Split each `render()` longer than ~80 lines into named section functions
  (filters, table, detail, charts, ...). It reads top to bottom as an
  outline. Pure refactor.
- `overview.game_card` moves to `lib/cards.py` (`views/games.py` must not
  import another view).
- `theme.rgba(hex_color, alpha) -> str`. Replace the hand-written rgba
  strings in `viz.py` (~238, 243, 477-479).
  - `media.py`'s `"#3987e5"` → `T.ACCENT`, `app.py`'s `"#898781"` →
    `T.MUTED`, and `viz.py:311` → `T.team_color()`.
  - Watch for circular imports between theme and media: if needed, pass
    colours in.
- Session-state keys used by views, if any beyond the Arcade, become
  module constants.
- Acceptance:
  - every page renders in AppTest;
  - pytest, ruff and mypy are green;
  - screenshots of Overview, Players, Teams, Games and Finances match
    before and after. Use Playwright with the `msedge` channel and a local
    `streamlit run` on a spare port. Compare visually; minor
    anti-aliasing differences are fine.
- Commit: "Break long page functions into sections and use theme tokens".

### Task 17: Docs

**Files:** `README.md`, `DEPLOYMENT.md`, new `CONTRIBUTING.md`, new ADRs
`docs/adr/0007-*.md` onwards, `docs/adr/0006-known-limitations.md`,
`docs/architecture.excalidraw`.

- `CONTRIBUTING.md`:
  - setup on Python 3.12 (`py -3.12 -m venv .venv`,
    `pip-sync requirements.txt requirements-dev.txt`, `pre-commit install`);
  - how to recompile locks;
  - the `BIP_DATA_HOME` / `BIP_WAREHOUSE` env vars;
  - running tests: full vs CI-style, and the `full_warehouse` marker;
  - lint/type commands;
  - the expand-then-contract rule for warehouse changes;
  - commit style (no AI trailers).
- ADRs, in the same format as the existing ones:
  - 0007 Python 3.12 and locked dependencies;
  - 0008 dbt marts as the single source of truth;
  - 0009 atomic writes and building the warehouse in a copy;
  - 0010 the data access package, caching and connection-per-query;
  - 0011 the shared `core` package and the team-codes seed.
- README: update the architecture and folder sections (the `core/`,
  `dashboard/lib/data/` and `views/arcade/` packages), the setup commands,
  the test counts, and "how the data refresh works" (copy-and-swap,
  `--no-publish`, accumulated play-by-play).
- DEPLOYMENT:
  - Python 3.12 on Streamlit Cloud (how to check and change it: the app's
    settings → Python version requires delete-and-redeploy; say exactly
    that);
  - the `.env` `BIP_DATA_HOME`;
  - the dry run;
  - logs location;
  - the lock file;
  - that `version.txt` is written after upload.
- 0006 known limitations: remove the items that are now fixed and add any
  new ones.
- Architecture diagram: update its nodes and edges to show `core/`, the
  data package, copy-and-swap, and the predictions CSV. It is Excalidraw
  JSON: edit it carefully and keep it valid JSON. Load it with Python
  `json` to verify.
- Commit: "Document the new structure, tooling and rollout".
