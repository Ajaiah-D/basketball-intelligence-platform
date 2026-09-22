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
    # home_points/away_points are carried here, even though the page never
    # displays them, because the settled-predictions join filters on them:
    # a cancelled game recorded as a 0-0 final is not a result and must not
    # be scored against the public track record.
    con.execute("""
        create table main_marts.fct_team_game (
            game_id varchar, margin double, home_won boolean,
            home_points integer, away_points integer
        )
    """)
    con.execute("""
        insert into predictions values
            ('p1', 'ridge-v1', '2026-09-20 12:00:00', 'g_upcoming', '2026-27',
             '2026-10-21', 1610612738, 1610612747, 3.5, 0.61),
            ('p2', 'ridge-v1', '2026-09-01 12:00:00', 'g_settled', '2026-27',
             '2026-09-05', 1610612738, 1610612747, 4.0, 0.63),
            ('p3', 'ridge-v1', '2026-09-01 12:00:00', 'g_no_contest', '2026-27',
             '2026-09-06', 1610612738, 1610612747, 4.0, 0.63)
    """)
    con.execute("""
        insert into main_staging.stg_schedule values
            ('g_upcoming', '2026-10-21', 'BOS', 'NYK', 1)
    """)
    # g_no_contest is the shape the one real cancelled game in the warehouse
    # takes: a 0-0 "final" that never happened. A prediction exists for it
    # (p3 above), so if the settled-predictions join ever loses its
    # exclusion, it gets graded as a definite miss on a 0 margin.
    con.execute("""
        insert into main_marts.fct_team_game values
            ('g_settled', 5.0, true, 110, 105),
            ('g_no_contest', 0.0, false, 0, 0)
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


def test_no_contest_game_is_not_scored_against_the_track_record(with_predictions_db):
    """A cancelled game recorded as a 0-0 final must not be graded.

    The fixture has two settled predictions, one of them for g_no_contest.
    Only g_settled is a real result, so n must be 1. Without the
    exclusion n is 2 and the extra row is scored as a confident miss (the
    model said home by 4, the "actual" margin is 0 and home_won is false),
    which drags accuracy to 0.5 and inflates Brier on a game that was
    never played.
    """
    record = db.prediction_track_record()
    assert record["n"] == 1, (
        "g_no_contest (0-0, cancelled) was scored; the settled-predictions "
        "join is missing its no-contest exclusion"
    )
    assert record["accuracy"] == 1.0


def test_renders_without_exception_when_predictions_table_is_absent(no_predictions_db):
    at = AppTest.from_string(SCRIPT)
    at.run()
    assert not at.exception
    assert len(at.get("dataframe")) == 0
