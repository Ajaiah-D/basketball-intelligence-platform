"""Shared fixtures. Tests run read-only against the real warehouse and
assert facts that are true of the data itself, not row counts that shift
on every refresh."""

import os
import sys
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Imported after the sys.path insert above - this conftest is what puts the
# repo root on the path in the first place, so a top-of-file import here
# would not resolve.
from dashboard.lib import db  # noqa: E402

DB_PATH = ROOT / "warehouse" / "basketball.duckdb"


@pytest.fixture(scope="session")
def con():
    if not DB_PATH.exists():
        # Locally a missing warehouse is a normal state - a developer who
        # has not run the pipeline yet - so skipping is right. In CI it is
        # a failure of the fixture-load step, and skipping there would let
        # the run go green while silently testing almost nothing: every
        # test behind this fixture (test_db_metrics.py's true-shooting era
        # guards, test_features.py's leakage checks) would skip, the ~19
        # synthetic-data tests would still pass, and pytest would exit 0.
        # GitHub Actions sets CI=true automatically.
        if os.environ.get("CI"):
            pytest.fail("warehouse missing in CI - the fixture load step did not run")
        pytest.skip("warehouse not built; run scripts/load_to_duckdb.py")
    connection = duckdb.connect(str(DB_PATH), read_only=True)
    yield connection
    connection.close()


# --- Finances page coverage ----------------------------------------------------
#
# Same isolated-tmp-warehouse pattern as test_predictions_page.py's
# no_predictions_db/with_predictions_db: a fresh DuckDB file per fixture,
# db.DB_PATH monkeypatched onto it, and the two db.py caches (q, and the
# relevant *_available()) cleared before and after so a stale hit from one
# test's warehouse can't leak into the next test's assertions against a
# different one.

def _reset_finances_cache() -> None:
    db.q.clear()
    db.team_finances_available.clear()


@pytest.fixture
def tmp_warehouse_without_marts(tmp_path, monkeypatch):
    """A warehouse file with no main_marts schema at all - the state of a
    warehouse published before mart_team_finances existed."""
    path = tmp_path / "no_marts.duckdb"
    duckdb.connect(str(path)).close()
    monkeypatch.setattr(db, "DB_PATH", path)
    _reset_finances_cache()
    yield path
    _reset_finances_cache()


@pytest.fixture
def warehouse_with_finances_mart(tmp_path, monkeypatch):
    """A warehouse with a minimal main_marts.mart_team_finances and
    main.salary_cap_history - enough to exercise team_payroll_history(),
    salary_cap_history() and the whole Finances page without touching the
    real warehouse.

    Deliberately covers every shape the page has to render:
      BOS/NYK - modern, complete, nothing flagged.
      DEN     - a 'sparse_source_data' season (1 salary row on record) next
                to a real one, so the source-gap caption has something to
                say and the chart still has a point to plot.
      MIA     - a 'below_half_cap' season: the 1988-89 inaugural expansion
                roster, 13 real players at 47% of the cap. Complete data, a
                genuinely low number - the case the page must NOT describe
                as missing source records.
      GOS/GSW - the same franchise either side of nba_api's 1996-97 code
                rename, which the page and team_payroll_history() have to
                return as one continuous series.
    """
    path = tmp_path / "with_finances.duckdb"
    con = duckdb.connect(str(path))
    con.execute("create schema main_marts")
    con.execute("""
        create table main.salary_cap_history (
            season varchar, salary_cap bigint, luxury_tax bigint,
            first_apron bigint, second_apron bigint
        )
    """)
    con.execute("""
        create table main_marts.mart_team_finances (
            season varchar, team_abbreviation varchar, team_payroll bigint,
            player_count integer, salary_cap bigint, luxury_tax bigint,
            first_apron bigint, second_apron bigint, payroll_pct_of_cap double,
            payroll_likely_incomplete boolean, payroll_incomplete_reason varchar,
            over_cap boolean, over_tax boolean,
            over_first_apron boolean, over_second_apron boolean
        )
    """)
    # 2022-23 predates the apron rules (first_apron/second_apron null, same
    # as salary_cap_history's real seed for that season); 2023-24 has both.
    # The pre-1996-97 rows use the real cap figures for those seasons.
    con.execute("""
        insert into main.salary_cap_history values
            ('1986-87', 4945000, NULL, NULL, NULL),
            ('1988-89', 7232000, NULL, NULL, NULL),
            ('1995-96', 23000000, NULL, NULL, NULL),
            ('1996-97', 24363000, NULL, NULL, NULL),
            ('2022-23', 123655000, 150267000, NULL, NULL),
            ('2023-24', 136021000, 165294000, 172346000, 182794000)
    """)
    con.execute("""
        insert into main_marts.mart_team_finances values
            ('2022-23', 'BOS', 178000000, 15, 123655000, 150267000, NULL, NULL,
             1.440, false, NULL, true, true, NULL, NULL),
            ('2023-24', 'BOS', 185000000, 15, 136021000, 165294000, 172346000, 182794000,
             1.360, false, NULL, true, true, true, false),
            ('2023-24', 'NYK', 150000000, 14, 136021000, 165294000, 172346000, 182794000,
             1.103, false, NULL, true, false, false, false),
            ('1986-87', 'DEN', 75000, 1, 4945000, NULL, NULL, NULL,
             0.015, true, 'sparse_source_data', false, NULL, NULL, NULL),
            ('1995-96', 'DEN', 24000000, 13, 23000000, NULL, NULL, NULL,
             1.043, false, NULL, true, NULL, NULL, NULL),
            ('1988-89', 'MIA', 3400000, 13, 7232000, NULL, NULL, NULL,
             0.470, true, 'below_half_cap', false, NULL, NULL, NULL),
            ('1995-96', 'MIA', 24500000, 14, 23000000, NULL, NULL, NULL,
             1.065, false, NULL, true, NULL, NULL, NULL),
            ('1995-96', 'GOS', 22000000, 13, 23000000, NULL, NULL, NULL,
             0.957, false, NULL, false, NULL, NULL, NULL),
            ('1996-97', 'GSW', 25000000, 14, 24363000, NULL, NULL, NULL,
             1.026, false, NULL, true, NULL, NULL, NULL)
    """)
    con.close()
    monkeypatch.setattr(db, "DB_PATH", path)
    _reset_finances_cache()
    yield path
    _reset_finances_cache()
