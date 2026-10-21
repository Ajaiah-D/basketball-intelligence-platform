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
from core import paths
from dashboard.lib import db

DB_PATH = paths.warehouse_path()


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


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """With CI set, fail the run if any test skipped.

    CI deselects the tests that need the full warehouse (-m "not
    full_warehouse"), so everything it does run should run. A skip there
    means a gap in the fixture warehouse is hiding a test, and the run goes
    green while testing less than it claims. Deselected tests are not skips
    and do not count. Locally, skips are fine.
    """
    if not os.environ.get("CI"):
        return
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    if reporter is None:
        return
    skipped = reporter.stats.get("skipped", [])
    if not skipped:
        return
    reporter.write_line("")
    reporter.write_sep("=", f"CI is set: {len(skipped)} skipped test(s) fail the run", red=True)
    for report in skipped:
        reason = report.longrepr[2] if isinstance(report.longrepr, tuple) else ""
        reporter.write_line(f"{report.nodeid}: {reason}")
    reporter.write_line(
        "Fix the skip, or mark the test full_warehouse if it needs the full local warehouse."
    )
    if exitstatus == pytest.ExitCode.OK:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


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
    db.team_contracts_available.clear()
    db.player_impact_available.clear()


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
            ('2023-24', 'BOS', 180000000, 15, 136021000, 165294000, 172346000, 182794000,
             1.323, false, NULL, true, true, true, false),
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
    # Rows scraped after fetch dates were recorded carry one.
    con.execute(
        "alter table main_marts.mart_team_finances add column payroll_fetched_at_utc timestamp"
    )
    con.execute(
        "update main_marts.mart_team_finances "
        "set payroll_fetched_at_utc = timestamp '2026-09-23 20:58:40'"
    )
    con.execute("""
        create table main_marts.mart_team_contracts as
        select * from (values
            ('2023-24', 'BOS', 'one01', 'Player One', 45000000, 1, 0.25),
            ('2023-24', 'BOS', 'two01', 'Player Two', 27000000, 2, 0.15),
            ('2023-24', 'BOS', 'three01', 'Player Three', 18000000, 3, 0.10)
        ) t(season, team_abbreviation, bbref_player_id, player, salary_usd,
            salary_rank, share_of_payroll)
    """)
    con.close()
    monkeypatch.setattr(db, "DB_PATH", path)
    _reset_finances_cache()
    yield path
    _reset_finances_cache()


@pytest.fixture
def legacy_finances_warehouse(warehouse_with_finances_mart):
    """The same warehouse as published before per-player salaries existed:
    no contracts mart and no fetch date. The deployed app reads whatever the
    last release published, so the page has to keep working on this."""
    con = duckdb.connect(str(warehouse_with_finances_mart))
    con.execute("drop table main_marts.mart_team_contracts")
    con.execute("alter table main_marts.mart_team_finances drop column payroll_fetched_at_utc")
    con.close()
    _reset_finances_cache()
    yield warehouse_with_finances_mart


@pytest.fixture
def warehouse_with_player_impact(tmp_path, monkeypatch):
    """A tiny warehouse holding main.player_impact (20 synthetic rows, 10 in
    each of 2023-24 and 2024-25) and its one-row main.player_impact_meta, the
    tables ml/player_impact.py writes. Player ids 1..10 appear in both seasons
    so all-time mode has the same player in two different seasons. Impact
    falls with the id, so ordering by impact desc is ordering by id.

    Built to be extended: the Arcade page tests add their own tables (e.g. a
    tiny main_marts.mart_team_season) by opening this file after the fixture.
    """
    path = tmp_path / "with_player_impact.duckdb"
    con = duckdb.connect(str(path))
    con.execute("""
        create table main.player_impact (
            season varchar, player_id bigint, player varchar, team varchar,
            gp integer, mpg double, ppg double, rpg double, apg double,
            impact double, usage double, cost integer
        )
    """)
    rows = []
    for season, shift in (("2023-24", 0.0), ("2024-25", 0.25)):
        for pid in range(1, 11):
            rows.append(
                (
                    season,
                    pid,
                    f"Player {pid}",
                    "BOS" if pid % 2 else "CHI → BOS",
                    60 + pid,
                    36.0 - pid,
                    30.0 - pid,
                    8.0 - pid / 2,
                    6.0 - pid / 3,
                    round(6.0 - pid * 0.5 - shift, 2),
                    round(1.5 - pid * 0.08, 2),
                    max(1, 11 - pid),
                )
            )
    con.executemany("insert into main.player_impact values (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    con.execute("""
        create table main.player_impact_meta (
            fitted_at timestamp, n_train integer, holdout_corr double,
            team_scale double, team_offset double, team_r2 double,
            team_mae double, usage_league_total double, coef_json varchar
        )
    """)
    con.execute("""
        insert into main.player_impact_meta values
        (timestamp '2026-10-01 12:00:00', 5000, 0.62, 1.9, -0.4, 0.71, 2.3, 5.0, '{}')
    """)
    con.close()
    monkeypatch.setattr(db, "DB_PATH", path)
    _reset_finances_cache()
    yield path
    _reset_finances_cache()


@pytest.fixture
def warehouse_for_team_builder(warehouse_with_player_impact):
    """warehouse_with_player_impact plus what the Arcade's Build a team tab
    reads on top of it:

      - a tiny main_marts.mart_team_season (season, team_abbreviation,
        team_id, net_rating): six teams in each of 2023-24 and 2024-25, one
        with no net rating, and a 1984-85 row that all_team_net_ratings()
        must leave out (it starts at 1985-86, like the impact pool);
      - 50 more 2024-25 player-seasons (ids 11..60, impact below every base
        row, cost 1), so a 6-team, 8-round draft (48 picks) has enough
        players to finish;
      - a gentler team calibration (scale 0.5, offset -6.0) than the base
        fixture's, so a valid 40-credit roster (ids 3..10) rates about +0.8
        and projects mid-range (about 40 wins) instead of saturating at 82-0,
        which would make the page's determinism check meaningless.
    """
    con = duckdb.connect(str(warehouse_with_player_impact))
    con.execute("create schema main_marts")
    con.execute("""
        create table main_marts.mart_team_season (
            season varchar, team_abbreviation varchar, team_id bigint,
            net_rating double
        )
    """)
    teams = [
        ("BOS", 1, 8.0),
        ("CHI", 2, 3.5),
        ("NYK", 3, 1.0),
        ("MIA", 4, -2.5),
        ("DET", 5, -7.0),
        ("LAL", 6, None),
    ]
    rows = [
        (s, abbr, tid, None if net is None else net + shift)
        for s, shift in (("2023-24", 0.0), ("2024-25", 0.5))
        for abbr, tid, net in teams
    ]
    rows.append(("1984-85", "BOS", 1, 9.9))
    con.executemany("insert into main_marts.mart_team_season values (?,?,?,?)", rows)
    extra = [
        (
            "2024-25",
            pid,
            f"Player {pid}",
            "NYK",
            50,
            20.0,
            8.0,
            3.0,
            1.5,
            round(-1.0 - pid * 0.01, 2),
            0.9,
            1,
        )
        for pid in range(11, 61)
    ]
    con.executemany("insert into main.player_impact values (?,?,?,?,?,?,?,?,?,?,?,?)", extra)
    con.execute("update main.player_impact_meta set team_scale = 0.5, team_offset = -6.0")
    con.close()
    _reset_finances_cache()
    yield warehouse_with_player_impact
    _reset_finances_cache()
