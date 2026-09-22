"""Headless checks that dashboard/views/predictions.py never crashes, in
either warehouse state a real deploy can be in: predictions already
published, and none published yet (a warehouse built before ml/predict.py
ever ran)."""

import duckdb
import pytest
from streamlit.testing.v1 import AppTest

from dashboard.lib import db

SCRIPT = """
from dashboard.views import predictions
predictions.render()
"""


def _reset_cache() -> None:
    # q() and predictions_available() cache on their arguments alone, not on
    # DB_PATH, so a stale hit from one test's warehouse would otherwise leak
    # into the next test's assertions against a different one.
    db.q.clear()
    db.predictions_available.clear()


@pytest.fixture
def no_predictions_db(tmp_path, monkeypatch):
    """A warehouse with no `predictions` table at all."""
    path = tmp_path / "no_predictions.duckdb"
    duckdb.connect(str(path)).close()
    monkeypatch.setattr(db, "DB_PATH", path)
    _reset_cache()
    yield path
    _reset_cache()


@pytest.fixture
def with_predictions_db(tmp_path, monkeypatch):
    """A warehouse with one upcoming prediction and one settled one."""
    path = tmp_path / "with_predictions.duckdb"
    con = duckdb.connect(str(path))
    con.execute("create schema main_staging")
    con.execute("create schema main_marts")
    con.execute("""
        create table predictions (
            prediction_id varchar, model_version varchar,
            predicted_at timestamp, game_id varchar, season varchar,
            game_date date, home_team_id bigint, away_team_id bigint,
            predicted_margin double, win_probability double
        )
    """)
    con.execute("""
        create table main_staging.stg_schedule (
            game_id varchar, game_date date,
            home_team_abbreviation varchar, away_team_abbreviation varchar,
            game_status integer
        )
    """)
    con.execute("""
        create table main_marts.fct_team_game (
            game_id varchar, margin double, home_won boolean
        )
    """)
    con.execute("""
        insert into predictions values
            ('p1', 'ridge-v1', '2026-09-20 12:00:00', 'g_upcoming', '2026-27',
             '2026-10-21', 1610612738, 1610612747, 3.5, 0.61),
            ('p2', 'ridge-v1', '2026-09-01 12:00:00', 'g_settled', '2026-27',
             '2026-09-05', 1610612738, 1610612747, 4.0, 0.63)
    """)
    con.execute("""
        insert into main_staging.stg_schedule values
            ('g_upcoming', '2026-10-21', 'BOS', 'NYK', 1)
    """)
    con.execute("""
        insert into main_marts.fct_team_game values ('g_settled', 5.0, true)
    """)
    con.close()
    monkeypatch.setattr(db, "DB_PATH", path)
    _reset_cache()
    yield path
    _reset_cache()


def test_renders_without_exception_when_predictions_exist(with_predictions_db):
    at = AppTest.from_string(SCRIPT)
    at.run()
    assert not at.exception
    # The upcoming-games table renders (one settled prediction, scored,
    # feeds the track record KPIs instead of a second table).
    assert len(at.get("dataframe")) == 1
    # Asserting only the dataframe count above would still pass if
    # prediction_track_record() silently returned {"n": 0} (e.g. an import
    # crash, or an over-broad exception guard swallowing a real error) and
    # the page fell back to the early-return "no predictions settled yet"
    # st.info - that branch renders zero dataframes too, same as this one.
    # Check the KPI markdown actually rendered, not just that nothing
    # raised, so this test can tell the two branches apart.
    markdown_text = " ".join(md.value for md in at.get("markdown"))
    assert "Accuracy" in markdown_text, (
        "the track-record KPI branch must have rendered; if this fails "
        "while at.exception is falsy, prediction_track_record() likely "
        "fell back to {'n': 0} instead of returning real metrics"
    )


def test_renders_without_exception_when_predictions_table_is_absent(no_predictions_db):
    at = AppTest.from_string(SCRIPT)
    at.run()
    assert not at.exception
    assert len(at.get("dataframe")) == 0
