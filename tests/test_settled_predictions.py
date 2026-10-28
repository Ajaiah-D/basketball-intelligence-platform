"""The graded predictions, read from dbt's mart_settled_predictions by both
the dashboard and ml/evaluate.py. These check the mart's grading rules on
synthetic games and on real ones, and that the dashboard's track record is
ml's numbers (the dashboard can't import ml, so the two score separately)."""

import shutil

import duckdb
import pandas as pd
import pytest

from core import paths
from dashboard.lib.data import core as data_core
from dashboard.lib.data import predictions
from ml import evaluate
from ml.train import evaluate as ml_metrics


@pytest.fixture
def synthetic_warehouse(tmp_path, add_settled_mart):
    """Predictions and results shaped to exercise every rule of the mart: a
    game predicted twice (only the first is graded), a tie on predicted_at
    (prediction_id decides), a no-contest 0-0 game, and a prediction for a
    game not yet played."""
    path = tmp_path / "settled.duckdb"
    con = duckdb.connect(str(path))
    con.execute("create schema main_marts")
    con.execute("""
        create table main.predictions (
            prediction_id varchar, model_version varchar,
            predicted_at timestamp, game_id varchar, season varchar,
            game_date date, home_team_id bigint, away_team_id bigint,
            predicted_margin double, win_probability double
        )
    """)
    con.execute("""
        create table main_marts.fct_team_game (
            game_id varchar, margin integer, home_won boolean,
            home_points integer, away_points integer
        )
    """)
    con.execute("""
        insert into main.predictions values
            ('a1', 'ridge-v1', '2026-10-01 12:00', 'g1', '2026-27', '2026-10-21', 1, 2, 3.0, 0.60),
            ('a2', 'ridge-v1', '2026-10-08 12:00', 'g1', '2026-27', '2026-10-21', 1, 2, -2.0, 0.40),
            ('b2', 'ridge-v2', '2026-10-01 12:00', 'g2', '2026-27', '2026-10-22', 3, 4, 1.0, 0.52),
            ('b1', 'ridge-v1', '2026-10-01 12:00', 'g2', '2026-27', '2026-10-22', 3, 4, -1.0, 0.48),
            ('c1', 'ridge-v1', '2026-10-01 12:00', 'g3', '2026-27', '2026-10-23', 5, 6, 4.0, 0.63),
            ('d1', 'ridge-v1', '2026-10-01 12:00', 'g4', '2026-27', '2026-10-30', 7, 8, 2.0, 0.55)
    """)
    con.execute("""
        insert into main_marts.fct_team_game values
            ('g1', 7, true, 110, 103),
            ('g2', -4, false, 99, 103),
            ('g3', 0, false, 0, 0)
    """)
    add_settled_mart(con)
    con.close()
    with data_core.use_warehouse(path):
        yield path


def test_the_mart_applies_every_grading_rule(synthetic_warehouse):
    settled = predictions.settled_predictions()
    # g1 graded on its first prediction, g2 on b1 (the tie on predicted_at
    # goes to prediction_id), g3 is a no-contest and g4 is unplayed.
    assert settled[["game_id", "win_probability"]].values.tolist() == [
        ["g1", 0.60],
        ["g2", 0.48],
    ]


@pytest.fixture
def mart_only_warehouse(tmp_path):
    """The mart as a plain table and nothing it is built from: whatever the
    dashboard returns can only have come from the mart."""
    path = tmp_path / "mart_only.duckdb"
    with duckdb.connect(str(path)) as con:
        con.execute("create schema main_marts")
        con.execute("create schema main_staging")
        con.execute("""
            create table main_marts.mart_settled_predictions as
            select * from (values
                ('g1', 'ridge-v1', date '2026-10-21', 3.0, 0.60, 7, true, 110, 103),
                ('g2', 'ridge-v1', date '2026-10-22', -1.0, 0.48, -4, false, 99, 103),
                ('g3', 'ridge-v1', date '2026-10-23', 2.0, 0.70, -2, false, 100, 102)
            ) t(game_id, model_version, game_date, predicted_margin, win_probability,
                margin, home_won, home_points, away_points)
        """)
        con.execute("""
            create table main_staging.stg_schedule as
            select * from (values
                ('g1', date '2026-10-21', 'BOS', 'NYK'),
                ('g2', date '2026-10-22', 'LAL', 'PHI'),
                ('g3', date '2026-10-23', 'MIA', 'DEN')
            ) t(game_id, game_date, home_team_abbreviation, away_team_abbreviation)
        """)
    with data_core.use_warehouse(path):
        yield path


def test_the_dashboard_reads_the_graded_games_from_the_mart(mart_only_warehouse):
    assert predictions.settled_available()
    settled = predictions.settled_predictions()
    assert settled["game_id"].tolist() == ["g1", "g2", "g3"]
    record = predictions.prediction_track_record()
    # g1 and g2 called right, g3's 70% home pick lost.
    assert record["n"] == 3
    assert record["accuracy"] == pytest.approx(2 / 3)
    assert record["brier"] == pytest.approx((0.4**2 + 0.48**2 + 0.7**2) / 3)
    assert record["margin_mae"] == pytest.approx((4 + 3 + 4) / 3)
    recent = predictions.recent_settled_predictions()
    assert recent["away"].tolist() == ["DEN", "PHI", "NYK"]  # newest first
    assert recent["correct"].tolist() == [False, True, True]


def test_a_warehouse_without_the_mart_has_no_track_record(tmp_path):
    # A warehouse published before the mart: the raw tables are there, but
    # the dashboard grades nothing itself any more.
    path = tmp_path / "no_mart.duckdb"
    with duckdb.connect(str(path)) as con:
        con.execute("create schema main_marts")
        con.execute("create table main.predictions (game_id varchar, win_probability double)")
        con.execute("insert into main.predictions values ('g1', 0.6)")
        con.execute("create table main_marts.fct_team_game (game_id varchar, home_won boolean)")
        con.execute("insert into main_marts.fct_team_game values ('g1', true)")
    with data_core.use_warehouse(path):
        assert not predictions.settled_available()
        assert predictions.settled_predictions().empty
        assert predictions.prediction_track_record() == {"n": 0}
        assert predictions.recent_settled_predictions().empty


# ml.train.evaluate clips probabilities to [1e-6, 1 - 1e-6] for log loss and
# scores Brier on the clipped values; the dashboard scores the raw ones. Each
# game's squared error moves by at most 2e-6 that way, so the averages stay
# within this of each other.
BRIER_CLIP_TOLERANCE = 1e-6


def _assert_same_record(dashboard: dict, ml: dict) -> None:
    assert dashboard["n"] == ml["n"]
    assert dashboard["accuracy"] == ml["accuracy"]
    assert dashboard["margin_mae"] == pytest.approx(ml["margin_mae"], rel=1e-12)
    assert dashboard["brier"] == pytest.approx(ml["brier"], rel=0, abs=BRIER_CLIP_TOLERANCE)


def test_the_track_record_is_ml_s_metrics(synthetic_warehouse):
    # Three more graded games on top of the fixture's two, at the edges of
    # the math: a coin flip (counts as a home pick), and a certain home win
    # and a certain home loss that both went the other way (the clip).
    with duckdb.connect(str(synthetic_warehouse)) as con:
        con.execute("""
            insert into main.predictions values
                ('e1', 'ridge-v1', '2026-10-01 12:00', 'g5', '2026-27', '2026-10-24', 1, 3, 0.0, 0.5),
                ('f1', 'ridge-v1', '2026-10-01 12:00', 'g6', '2026-27', '2026-10-24', 2, 4, 9.0, 1.0),
                ('h1', 'ridge-v1', '2026-10-01 12:00', 'g7', '2026-27', '2026-10-25', 5, 7, -9.0, 0.0)
        """)
        con.execute("""
            insert into main_marts.fct_team_game values
                ('g5', -1, false, 100, 101),
                ('g6', -3, false, 97, 100),
                ('g7', 12, true, 120, 108)
        """)
    data_core.clear_caches()
    settled = predictions.settled_predictions()
    assert len(settled) == 5
    record = predictions.prediction_track_record()
    expected = ml_metrics(settled)
    _assert_same_record(record, expected)
    # Hand-checked: g1 and g2 called right; g5's coin flip picks home, who
    # lost; g6 and g7 called wrong.
    assert record["accuracy"] == pytest.approx(2 / 5)


@pytest.fixture(scope="module")
def warehouse_copy(con, tmp_path_factory):
    """A copy of the real warehouse (CI's fixture one in CI) with synthetic
    predictions added for real played games: two home wins and two home
    losses, one game predicted twice (only the first counts) and one with
    two predictions stamped at the same moment (prediction_id decides). The
    mart is a view, so nothing needs rebuilding. The copy keeps the file
    name: dbt-duckdb's views name the catalog after it."""
    source = paths.warehouse_path()
    path = tmp_path_factory.mktemp("settled") / source.name
    shutil.copyfile(source, path)
    with duckdb.connect(str(path), read_only=True) as ro:
        built = ro.execute(
            "select count(*) from information_schema.tables "
            "where table_schema = 'main_marts' and table_name = 'mart_settled_predictions'"
        ).fetchone()
    if not built or not built[0]:
        # A local warehouse published before the model existed. CI always
        # builds dbt fresh, and its skip guard fails any skip there.
        pytest.skip("this warehouse predates mart_settled_predictions; run dbt build")
    with duckdb.connect(str(path)) as rw:
        games = rw.execute(
            """
            (select game_id, season, game_date, home_team_id, away_team_id
             from main_marts.fct_team_game
             where home_won and not (home_points = 0 and away_points = 0)
               and game_id not in (select game_id from main.predictions)
             order by game_id limit 2)
            union all
            (select game_id, season, game_date, home_team_id, away_team_id
             from main_marts.fct_team_game
             where not home_won and not (home_points = 0 and away_points = 0)
               and game_id not in (select game_id from main.predictions)
             order by game_id limit 2)
            """
        ).fetchall()
        assert len(games) == 4, "the warehouse needs two home wins and two home losses"
        rows = []
        for i, (game_id, season, game_date, home, away) in enumerate(games):
            rows.append(
                (
                    f"test-{i}-b",
                    "ridge-v1",
                    "2000-01-01 12:00",
                    game_id,
                    season,
                    game_date,
                    home,
                    away,
                    2.0 + i,
                    0.55 + i / 100,
                )
            )
        first, tied = games[0], games[1]
        # A later re-run of the first game, and a same-moment rival for the
        # second whose prediction_id sorts after test-1-b.
        rows.append(
            (
                "test-0-z",
                "ridge-v1",
                "2000-02-01 12:00",
                first[0],
                first[1],
                first[2],
                first[3],
                first[4],
                -9.0,
                0.10,
            )
        )
        rows.append(
            (
                "test-1-z",
                "ridge-v2",
                "2000-01-01 12:00",
                tied[0],
                tied[1],
                tied[2],
                tied[3],
                tied[4],
                -8.0,
                0.20,
            )
        )
        rw.executemany(
            "insert into main.predictions (prediction_id, model_version, predicted_at, "
            "game_id, season, game_date, home_team_id, away_team_id, predicted_margin, "
            "win_probability) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
    expected = {g[0]: 0.55 + i / 100 for i, g in enumerate(games)}
    with data_core.use_warehouse(path):
        yield path, expected


def _the_model(path) -> pd.DataFrame:
    with duckdb.connect(str(path), read_only=True) as con:
        return con.execute(
            "select * from main_marts.mart_settled_predictions order by game_id"
        ).df()


def test_the_mart_grades_real_games_on_their_first_prediction(warehouse_copy):
    path, expected = warehouse_copy
    dashboard = predictions.settled_predictions()
    pd.testing.assert_frame_equal(dashboard, _the_model(path))
    # The synthetic games are in, each graded on its first prediction.
    graded = dashboard.set_index("game_id").loc[list(expected), "win_probability"]
    assert graded.round(6).to_dict() == {g: round(p, 6) for g, p in expected.items()}
    assert set(dashboard.set_index("game_id").loc[list(expected), "home_won"]) == {True, False}


def test_ml_evaluate_grades_the_same_games(warehouse_copy):
    path, _ = warehouse_copy
    with duckdb.connect(str(path), read_only=True) as con:
        graded = evaluate.settled_predictions(con)
    dashboard = predictions.settled_predictions()[graded.columns]
    pd.testing.assert_frame_equal(graded, dashboard)


def test_ml_and_the_dashboard_score_the_same_track_record(warehouse_copy):
    path, _ = warehouse_copy
    with duckdb.connect(str(path), read_only=True) as con:
        ml = evaluate.track_record(con)
    _assert_same_record(predictions.prediction_track_record(), ml)
