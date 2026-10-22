"""The settled-predictions query exists twice: as dbt's
mart_settled_predictions, which ml/evaluate.py reads, and as the dashboard's
own copy in dashboard/lib/data/predictions.py, which stays until a warehouse
with the model is published. These tests fail the moment the two differ, in
text or in output."""

import re

import duckdb
import pandas as pd
import pytest

from core import paths
from dashboard.lib.data import core as data_core
from dashboard.lib.data import predictions
from ml import evaluate

MODEL = (
    paths.PROJECT_ROOT
    / "dbt"
    / "basketball_intelligence"
    / "models"
    / "marts"
    / "mart_settled_predictions.sql"
)


def _model_query() -> str:
    """The model's real query (the branch built when main.predictions exists),
    with its Jinja references written out as the tables they resolve to."""
    text = MODEL.read_text(encoding="utf-8")
    match = re.search(r"\{%-? else -?%\}(.*)\{%-? endif -?%\}", text, re.S)
    assert match, "mart_settled_predictions.sql lost its else/endif branch"
    return (
        match.group(1)
        .replace("{{ predictions }}", "main.predictions")
        .replace("{{ ref('fct_team_game') }}", "main_marts.fct_team_game")
    )


def _normalized(sql: str) -> str:
    without_comments = re.sub(r"--[^\n]*", "", sql)
    return " ".join(without_comments.split())


def test_the_dashboard_query_is_the_model_word_for_word():
    query = _model_query()
    assert "{{" not in query and "{%" not in query, "an unresolved Jinja reference"
    assert _normalized(predictions.SETTLED_PREDICTIONS_SQL) == _normalized(query)


@pytest.fixture
def synthetic_warehouse(tmp_path):
    """Predictions and results shaped to exercise every rule of the query: a
    game predicted twice (only the first is graded), a later re-run stamped
    first by prediction_id order on a tie, a no-contest 0-0 game, and a
    prediction for a game not yet played. The model's query is installed as
    the view dbt would build."""
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
    con.execute(f"create view main_marts.mart_settled_predictions as {_model_query()}")
    con.close()
    with data_core.use_warehouse(path):
        yield path


def test_the_rules_hold_on_synthetic_games(synthetic_warehouse):
    settled = predictions.settled_predictions()
    # g1 graded on its first prediction, g2 on b1 (the tie on predicted_at
    # goes to prediction_id), g3 is a no-contest and g4 is unplayed.
    assert settled[["game_id", "win_probability"]].values.tolist() == [
        ["g1", 0.60],
        ["g2", 0.48],
    ]


def _the_model(path) -> pd.DataFrame:
    with duckdb.connect(str(path), read_only=True) as con:
        return con.execute(
            "select * from main_marts.mart_settled_predictions order by game_id"
        ).df()


def test_dashboard_and_model_agree_on_synthetic_games(synthetic_warehouse):
    pd.testing.assert_frame_equal(
        predictions.settled_predictions(), _the_model(synthetic_warehouse)
    )


def test_ml_evaluate_grades_the_same_games(synthetic_warehouse):
    with duckdb.connect(str(synthetic_warehouse), read_only=True) as con:
        graded = evaluate.settled_predictions(con)
    dashboard = predictions.settled_predictions()[graded.columns]
    pd.testing.assert_frame_equal(graded, dashboard)


def test_dashboard_and_model_agree_on_the_warehouse(con):
    """On the real warehouse (or CI's fixture one), the dbt-built model and
    the dashboard's copy return the same frame."""
    with data_core.use_warehouse(paths.warehouse_path()):
        pd.testing.assert_frame_equal(
            predictions.settled_predictions(), _the_model(paths.warehouse_path())
        )
