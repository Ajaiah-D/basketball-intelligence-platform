# 0011. The shared `core` package and the team-codes seed

**Status:** Accepted

## Context

Rules the whole project depends on were written out wherever they were
needed. The warehouse path was rebuilt from `__file__` in about ten
modules across the scripts, the models, the dashboard and the tests. Facts about
team codes lived in four places: conference sets in `dashboard/lib/db.py`
and a `case` expression in `mart_team_standings.sql`, franchise names in
`dashboard/lib/franchises.py`, colours in `dashboard/lib/theme.py`, and
Basketball-Reference codes in `ingestion/team_payroll_ingest.py`. Season
boundaries (official advanced stats from 1996-97, complete box scores from
1985-86), the Elo settings and the game-margin spread were repeated as
literals. Accent-insensitive search folding was written three times, and
DuckDB's `strip_accents()` disagreed with the Python version on letters
like "ł" and "ø", so the same search could match on one page and miss on
another. Changing any of these meant finding every copy.

## Decision

Add a top-level `core/` package that every part of the project imports:

- `paths.py`: every path, the `BIP_DATA_HOME` and `BIP_WAREHOUSE`
  overrides, and the one place `.env` is loaded.
- `io.py`: crash-safe parquet writes and the transient-error retry loop
  (`0009-atomic-writes-and-building-the-warehouse-in-a-copy.md`).
- `constants.py`: season boundaries, the Elo settings, the margin spreads,
  the Arcade economy, the play-by-play cap and the health check thresholds,
  each with a comment saying where its value came from.
- `teams.py`: what a team code means in a given season.
- `seasons.py`: the season a date falls in (`current_season()`), so the
  health check gets it without importing the ingester and nba_api.
- `text.py`: `fold()`, the one search-folding rule. Searches fold in
  Python, not SQL, so both sides of a match fold the same way.
- `fmt.py`: money and ordinal formats.

`core/` imports only the standard library and `python-dotenv`, plus pandas
and pyarrow in `io.py` alone, so the deployed dashboard, the ingesters
(which run before dbt exists) and the tests can all import it.

Team-code facts live in one CSV, the dbt seed `team_codes.csv`: one row
per code and era, with its franchise, era name, conference, colour and
Basketball-Reference code. dbt joins it into `mart_team_standings`, and
`core/teams.py` reads the file directly rather than the warehouse, because
ingestion runs before dbt has built anything and the dashboard must not
depend on a table newer than the published warehouse. Lookups are by code
and season, never code alone, so a future team reusing an old code isn't
folded into the wrong franchise. dbt tests fail the build if a code in
the game logs or the payroll has no era.

Where two numbers look alike but measure different things, both are kept
and named: `PREDICTION_MARGIN_SD` (13.5, the prediction model's error) and
`GAME_MARGIN_SD` (12.7, the Arcade simulator's game-to-game noise).

Considered and rejected: making the project an installable package
(`pip install -e .`), which the app doesn't need and Streamlit Cloud
doesn't do (the scripts put the repo root on `sys.path` instead); keeping
team facts in a warehouse table only, which ingestion and an older
published warehouse can't see; and a Python dict as the source, which dbt
can't join.

## Consequences

A rule changes in one edit, and a test or dbt check guards each one. The
Docker image copies `core/` and the seed file alongside the dashboard. The
scripts need a `sys.path` line before their imports, which the lint config
allows file by file. The seed holds one conference per code era, so the
few historical realignments within one code (the New Orleans Hornets in
the East in 2002-03 and 2003-04, Milwaukee, Houston and San Antonio in
1979-80) still show the code's later conference
(`0006-known-limitations.md`); fixing one is now a row split in the CSV.
