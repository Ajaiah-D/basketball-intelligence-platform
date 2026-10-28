"""Shared fixtures. Tests run read-only against the real warehouse and
assert facts that are true of the data itself, not row counts that shift
on every refresh."""

import os
import sys
from pathlib import Path

import duckdb
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Imported after the sys.path insert above - this conftest is what puts the
# repo root on the path in the first place, so a top-of-file import here
# would not resolve.
from core import paths
from dashboard.lib.data import core as data_core

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
        # Only under -p no:terminal, which CI never passes: the guard is off then.
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


# --- Tiny warehouses for page tests ----------------------------------------------
#
# Same isolated-tmp-warehouse pattern as test_predictions_page.py's
# no_predictions_db/with_predictions_db: a fresh DuckDB file per fixture,
# with the whole dashboard pointed at it through use_warehouse(), which
# clears the caches on the way in and out so a stale hit from one test's
# warehouse can't leak into the next test's assertions against a different
# one.


def _reset_caches() -> None:
    """For a fixture or test that changes a warehouse file in place: the
    data layer's cache follows the file's mtime, but two writes can land in
    one tick of the filesystem clock."""
    data_core.clear_caches()


@pytest.fixture
def tmp_warehouse_without_marts(tmp_path):
    """A warehouse file with no main_marts schema at all - the state of a
    warehouse published before mart_team_finances existed."""
    path = tmp_path / "no_marts.duckdb"
    duckdb.connect(str(path)).close()
    with data_core.use_warehouse(path):
        yield path


@pytest.fixture
def warehouse_with_finances_mart(tmp_path):
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
    with data_core.use_warehouse(path):
        yield path


@pytest.fixture
def legacy_finances_warehouse(warehouse_with_finances_mart):
    """The same warehouse as published before per-player salaries existed:
    no contracts mart and no fetch date. The deployed app reads whatever the
    last release published, so the page has to keep working on this."""
    con = duckdb.connect(str(warehouse_with_finances_mart))
    con.execute("drop table main_marts.mart_team_contracts")
    con.execute("alter table main_marts.mart_team_finances drop column payroll_fetched_at_utc")
    con.close()
    _reset_caches()
    yield warehouse_with_finances_mart


@pytest.fixture
def warehouse_with_player_impact(tmp_path):
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
    with data_core.use_warehouse(path):
        yield path


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
    _reset_caches()
    yield warehouse_with_player_impact
    _reset_caches()


# --- A tiny season schedule --------------------------------------------------------
#
# For data/schedule.py and the Schedule page. One synthetic season covers the
# shapes: a tie for top scorer, a neutral-site game whose result is oriented
# the other way, a cancelled 0-0 game, a re-predicted game, a preseason game.
# A second, earlier season is scheduled too (one game), and the sidebar's list
# adds a season the schedule doesn't hold, for the page's season rules.

SCHEDULE_SEASON = "2030-31"
SCHEDULE_PRIOR_SEASON = "2029-30"
SCHEDULE_UNSCHEDULED_SEASON = "2028-29"

_SCHEDULE_IDS = {"BOS": 1, "NYK": 2, "MIA": 3, "DAL": 4}

# (game_id, date, tipoff_utc, home, away)
_SCHEDULE_GAMES = [
    ("0013000001", "2030-10-10", "2030-10-10 23:00:00", "BOS", "NYK"),  # preseason
    ("0023000001", "2030-10-20", "2030-10-20 23:30:00", "BOS", "NYK"),
    ("0023000002", "2030-10-22", "2030-10-23 00:00:00", "NYK", "BOS"),
    ("0023000003", "2030-10-22", "2030-10-22 19:00:00", "MIA", "DAL"),  # neutral
    ("0023000004", "2030-10-25", "2030-10-25 23:00:00", "BOS", "MIA"),  # upcoming
    ("0023000005", "2030-11-02", "2030-11-02 23:00:00", "BOS", "DAL"),  # cancelled
]

# fct_team_game rows: (game_id, home, away, home_points, away_points).
# The neutral game is oriented DAL-home there, the other way round.
_SCHEDULE_RESULTS = [
    ("0023000001", "BOS", "NYK", 112, 105),
    ("0023000002", "NYK", "BOS", 100, 99),
    ("0023000003", "DAL", "MIA", 90, 95),
    ("0023000005", "BOS", "DAL", 0, 0),
]

# (game_id, player, points)
_SCHEDULE_LOGS = [
    ("0023000001", "Zed Zulu", 30),
    ("0023000001", "Abe Able", 30),
    ("0023000001", "Cal Cole", 12),
    ("0023000002", "Cal Cole", 41),
    ("0023000003", "Dan Dee", None),
    ("0023000003", "Eli Eck", 22),
]

# (prediction_id, predicted_at, game_id, win_probability, predicted_margin)
_SCHEDULE_PREDICTIONS = [
    ("p1", "2030-10-19 10:00:00", "0023000001", 0.61, 3.0),
    ("p2", "2030-10-23 10:00:00", "0023000004", 0.55, 1.5),
    ("p3", "2030-10-24 10:00:00", "0023000004", 0.65, 5.0),
]


def _schedule_table(con, name, df):
    con.register("df_view", df)
    con.execute(f"create table {name} as select * from df_view")
    con.unregister("df_view")


def _build_schedule_warehouse(path, with_predictions=True):
    con = duckdb.connect(str(path))
    con.execute("create schema main_staging")
    con.execute("create schema main_marts")
    _schedule_table(
        con,
        "main_staging.stg_schedule",
        pd.DataFrame(
            [
                {
                    "season": SCHEDULE_SEASON,
                    "game_id": gid,
                    "game_date": pd.Timestamp(day).date(),
                    "tipoff_utc": pd.Timestamp(tip),
                    "home_team_id": _SCHEDULE_IDS[home],
                    "home_team_abbreviation": home,
                    "away_team_id": _SCHEDULE_IDS[away],
                    "away_team_abbreviation": away,
                    "game_status": 1 if gid == "0023000004" else 3,
                    "is_regular_season": gid.startswith("002"),
                }
                for gid, day, tip, home, away in _SCHEDULE_GAMES
            ]
            + [
                {
                    "season": SCHEDULE_PRIOR_SEASON,
                    "game_id": "0022900001",
                    "game_date": pd.Timestamp("2029-10-23").date(),
                    "tipoff_utc": pd.Timestamp("2029-10-23 23:00:00"),
                    "home_team_id": _SCHEDULE_IDS["MIA"],
                    "home_team_abbreviation": "MIA",
                    "away_team_id": _SCHEDULE_IDS["DAL"],
                    "away_team_abbreviation": "DAL",
                    "game_status": 3,
                    "is_regular_season": True,
                }
            ]
        ),
    )
    _schedule_table(
        con,
        "main_marts.fct_team_game",
        pd.DataFrame(
            [
                {
                    "season": SCHEDULE_SEASON,
                    "game_id": gid,
                    "home_team_id": _SCHEDULE_IDS[home],
                    "home_team_abbreviation": home,
                    "away_team_id": _SCHEDULE_IDS[away],
                    "away_team_abbreviation": away,
                    "home_points": hp,
                    "away_points": ap,
                }
                for gid, home, away, hp, ap in _SCHEDULE_RESULTS
            ]
        ),
    )
    logs = pd.DataFrame(_SCHEDULE_LOGS, columns=["game_id", "player_name", "points"])
    logs["season"] = SCHEDULE_SEASON
    logs["points"] = logs["points"].astype("Int64")
    _schedule_table(con, "main_staging.stg_player_game_logs", logs)
    # The sidebar season box (seasons.seasons()) reads this.
    _schedule_table(
        con,
        "main_staging.stg_team_game_logs",
        pd.DataFrame(
            {
                "season": [
                    SCHEDULE_SEASON,
                    SCHEDULE_PRIOR_SEASON,
                    SCHEDULE_UNSCHEDULED_SEASON,
                ]
            }
        ),
    )
    if with_predictions:
        preds = pd.DataFrame(
            _SCHEDULE_PREDICTIONS,
            columns=[
                "prediction_id",
                "predicted_at",
                "game_id",
                "win_probability",
                "predicted_margin",
            ],
        )
        preds["predicted_at"] = pd.to_datetime(preds["predicted_at"])
        _schedule_table(con, "main.predictions", preds)
    con.close()
    return path


@pytest.fixture
def schedule_warehouse(tmp_path):
    path = _build_schedule_warehouse(tmp_path / "schedule.duckdb")
    with data_core.use_warehouse(path):
        yield path


@pytest.fixture
def schedule_warehouse_without_predictions(tmp_path):
    path = _build_schedule_warehouse(
        tmp_path / "schedule_no_predictions.duckdb", with_predictions=False
    )
    with data_core.use_warehouse(path):
        yield path
