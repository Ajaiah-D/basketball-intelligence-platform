# Contributing

How to set up, run, test and change this project. The [README](README.md)
says what it is, and [DEPLOYMENT.md](DEPLOYMENT.md) how it runs live. The
reasons behind the rules here are in [docs/adr/](docs/adr/).

## Setup

Python 3.12 only (`pyproject.toml` says `>=3.12,<3.13`, and the lock files
are compiled for it). On Windows:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install pip-tools
pip-sync requirements.txt requirements-dev.txt
pre-commit install
```

`pip-sync` makes the venv match the lock files exactly, removing anything
they don't list. `pip install -r requirements.txt -r requirements-dev.txt`
works too, but leaves stray packages behind. `pre-commit install` adds the
git hook that lints each commit (see "Lint, format and types").

Copy `.env.example` to `.env` for the Dev Lab password and, optionally, the
data location variables below. `.env` is gitignored; never commit it.

## Dependencies and the lock files

| File | What it is |
|---|---|
| `requirements.in` | the app's direct dependencies, loosely pinned |
| `requirements.txt` | the runtime lock: every package, exact versions. Streamlit Cloud and the Docker image install this |
| `requirements-dev.in` | test, ML and lint tools (pytest, scikit-learn, scipy, ruff, mypy, pre-commit) |
| `requirements-dev.txt` | the dev lock. CI installs both locks |

The `.txt` files are generated; don't edit them by hand. To add or change a
dependency, edit the `.in` file, then recompile and sync:

```powershell
python -m piptools compile --strip-extras --output-file requirements.txt requirements.in
python -m piptools compile --strip-extras --output-file requirements-dev.txt requirements-dev.in
pip-sync requirements.txt requirements-dev.txt
```

Always compile the runtime lock first: `requirements-dev.in` starts with
`-c requirements.txt`, so the dev lock reuses the runtime versions of every
package the two share. To upgrade one package, add
`--upgrade-package <name>` to both compile commands; `--upgrade` moves
everything. Commit the `.in` and `.txt` files together, and read the lock
diff before you do.

Two rules:

- **The dashboard never imports `ml/`, `scripts/` or `ingestion/`.** Their
  dependencies (scikit-learn, scipy, nba_api) are dev-only, so the deployed
  app doesn't have them. `tests/test_import_boundaries.py` fails on any such
  import, including one inside a function.
- **DuckDB stays below 2.0** (`requirements.in`). A major DuckDB version can
  change the file format the live app downloads, so that upgrade is its own
  change, not a side effect of a recompile.

The locks are compiled on Windows and CI installs them on Linux. If a
recompile adds a Windows-only package, CI is where it shows up.

## Where the data lives

Two environment variables move the data. `core/paths.py` resolves every
path and reads `.env` once; a real environment variable beats a line in
`.env`.

| Variable | What it does |
|---|---|
| `BIP_DATA_HOME` | a folder that holds `raw/` (the parquet files) and `warehouse/` (the DuckDB file) instead of the repo |
| `BIP_WAREHOUSE` | one warehouse file. Wins over `BIP_DATA_HOME` for the warehouse; `raw/` still follows `BIP_DATA_HOME` |

With neither set, everything is under the repo (`data/raw/`,
`warehouse/basketball.duckdb`). A relative value is read relative to the
repo root, whatever folder you run from. Keep the data outside OneDrive or
any other sync folder: sync can lock a file while it's being written.

Some files never move, because they are committed: the predictions history
(`data/predictions/history.csv`), the test fixtures (`data/fixtures/`), the
run logs (`logs/`) and the team codes seed.

**dbt doesn't read `.env`.** `profiles.yml` reads `BIP_WAREHOUSE` from the
environment, and without it falls back to the repo's
`warehouse/basketball.duckdb`. So if you set `BIP_DATA_HOME`, export the
warehouse path before running dbt by hand, or dbt builds a different file
from the one the scripts and the dashboard read:

```powershell
$env:BIP_WAREHOUSE = python -c "from core import paths; print(paths.warehouse_path())"
cd dbt\basketball_intelligence
dbt build --profiles-dir .
```

Run the first line from the repo root. It prints an absolute path, which
matters: dbt runs from `dbt/basketball_intelligence`, so a relative path
would point somewhere else for dbt than for Python. The weekly refresh sets
`BIP_WAREHOUSE` itself (to its copy) for every step it runs.

## Running the tests

```powershell
python -m pytest -q                            # everything, against your local warehouse
python -m pytest -q -m "not full_warehouse"    # what CI runs
```

The full run is about 917 tests and takes about two minutes. Tests read the real
warehouse and assert facts that are true of the data itself, not row counts
that change every week.

CI can't reach stats.nba.com, so it builds a small warehouse from
`data/fixtures/` (real data, cut down to a few seasons; its
[README](data/fixtures/README.md) says what each file is for) and
deselects the 9 tests marked `full_warehouse`. It also sets `CI`, and then
any skipped test fails the run: a skip in CI means a gap in the fixtures is
hiding a test.

- **Mark a test `full_warehouse`** (`@pytest.mark.full_warehouse`) when it
  needs all seasons, such as fitting a model on the whole history. Don't
  make it skip instead: in CI that fails the run.
- **To reproduce CI exactly**, build the fixture warehouse in a scratch
  folder and point everything at it:

  ```powershell
  $env:BIP_DATA_HOME = "$env:TEMP\bip-ci"
  New-Item -ItemType Directory -Force "$env:BIP_DATA_HOME\raw"
  Copy-Item -Recurse -Force data\fixtures\* "$env:BIP_DATA_HOME\raw"
  python scripts\load_to_duckdb.py
  $env:BIP_WAREHOUSE = python -c "from core import paths; print(paths.warehouse_path())"
  cd dbt\basketball_intelligence; dbt build --profiles-dir .; cd ..\..
  $env:CI = "1"
  python -m pytest -q -m "not full_warehouse"
  ```

  Close that shell afterwards (or clear the three variables), or the next
  commands will run against the fixtures.
- **dbt's own tests** run with `dbt build`, after each model they cover.
  If you add a dbt test that names a specific team-season, add that
  team-season's rows to the fixtures too, or CI can't find them.

## Lint, format and types

```powershell
ruff check .            # lint (add --fix to apply the safe fixes)
ruff format .           # format; CI runs ruff format --check .
mypy                    # type check the packages listed in pyproject.toml
pre-commit run --all-files
```

All three are configured in `pyproject.toml`, and CI runs them before any
test. The pre-commit hook runs ruff, ruff format, mypy and the whitespace
checks on every commit. It uses the venv's own pinned tools, so activate the
venv before you commit. Typing is gradual: unannotated functions are still
checked, but nothing is forced to carry annotations.

`core/` imports only the standard library and `python-dotenv` (plus pandas
and pyarrow in `core/io.py`), so every part of the project can import it,
the deployed dashboard included; the same test holds it to that.

## Changing the warehouse: expand, then contract

Code and data ship separately. Code reaches the live app on a push to
`main`; data reaches it only when a refresh publishes a new warehouse. So
for a while after every merge, the live app runs new code against last
week's warehouse. A warehouse change therefore goes in three steps:

1. **Expand.** Add the new model or column. Never drop or rename a table or
   column that the code on `main` reads. Merge, then publish (run the
   refresh, or wait for Tuesday's).
2. **Switch the readers.** Once the published warehouse has the new
   object, change the code to read it. A reader that may still meet an
   older warehouse checks with `objects_exist()` first and shows a notice
   instead of an error.
3. **Contract.** Remove the old object only when nothing on `main` reads
   it any more.

"Additive" also means checking what the live code does with the table. When
`mart_player_season` gained a column, the planned name was `team_path`. The
deployed Advanced page reads that mart with `select *` and then merges in
its own `team_path` column, so pandas would have produced `team_path_x` and
`team_path_y` and the page would have crashed on the next publish. The
column is called `team_label` instead. A new column can collide with a
name the old code adds itself.

`mart_settled_predictions` (the graded predictions) is a worked example.
It was newer than the published warehouse, so for one release the
dashboard kept its own copy of the same SQL, with a test that failed if
the two differed. Once a refresh had published the mart, the dashboard
switched to reading it, and the copy and the test were deleted. Until a
new mart is published, a page that reads it checks
`data.core.objects_exist(...)` and shows a one-line notice.

The reasoning is in
[ADR 0008](docs/adr/0008-dbt-marts-as-the-single-source-of-truth.md).

## Commit style

- An imperative subject line under about 72 characters ("Fold search text
  in one place"), then a short body that says why.
- One logical change per commit.
- No AI attribution: no `Co-Authored-By` trailers or "generated with"
  lines. No emoji (the README title carries the project's one).
- Comments explain why, not what. Public functions have docstrings.
- Never commit `.env`, the warehouse, or `data/raw/`.
