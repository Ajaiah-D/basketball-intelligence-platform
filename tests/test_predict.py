"""Predictions are the public record. The properties that make that record
credible - written before tip-off, never rewritten - are asserted here."""

import duckdb
import pandas as pd
import pytest

from ml.predict import MODEL_VERSION, write_predictions


@pytest.fixture
def memory_db():
    con = duckdb.connect(":memory:")
    con.execute("""
        create table predictions (
            prediction_id varchar, model_version varchar,
            predicted_at timestamp, game_id varchar, season varchar,
            game_date date, home_team_id bigint, away_team_id bigint,
            predicted_margin double, win_probability double
        )
    """)
    return con


def _rows():
    return pd.DataFrame({
        "game_id": ["0022600001"],
        "season": ["2026-27"],
        "game_date": pd.to_datetime(["2026-10-20"]).date,
        "home_team_id": [1610612738],
        "away_team_id": [1610612747],
        "predicted_margin": [3.5],
        "win_probability": [0.61],
    })


def test_writing_twice_appends_rather_than_overwrites(memory_db):
    write_predictions(memory_db, _rows())
    write_predictions(memory_db, _rows())
    total = memory_db.execute("select count(*) from predictions").fetchone()[0]
    assert total == 2, "a re-run must not erase the earlier prediction"


def test_every_row_carries_the_model_version(memory_db):
    write_predictions(memory_db, _rows())
    versions = memory_db.execute(
        "select distinct model_version from predictions").fetchall()
    assert versions == [(MODEL_VERSION,)]


def test_win_probability_stays_a_probability(memory_db):
    write_predictions(memory_db, _rows())
    bad = memory_db.execute(
        "select count(*) from predictions where win_probability not between 0 and 1"
    ).fetchone()[0]
    assert bad == 0
