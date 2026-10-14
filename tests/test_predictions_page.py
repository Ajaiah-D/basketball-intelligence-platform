"""Headless checks that dashboard/views/predictions.py never crashes, in
every warehouse state a real deploy can be in: predictions already
published and settled, published but nothing settled yet, and none published
yet (a warehouse built before ml/predict.py ever ran)."""

import re

import duckdb
import numpy as np
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


def _build_warehouse(path, settled: bool = True) -> None:
    """Write a small warehouse: two upcoming games (one with a tip-off time,
    one without) and, when `settled`, a graded game plus a no-contest."""
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
            game_id varchar, game_date date, tipoff_utc timestamp,
            home_team_abbreviation varchar, away_team_abbreviation varchar,
            game_status integer
        )
    """)
    # home_points/away_points are carried here because the settled-predictions
    # join filters on them: a cancelled game recorded as a 0-0 final is not a
    # result and must not be scored against the public track record.
    con.execute("""
        create table main_marts.fct_team_game (
            game_id varchar, margin double, home_won boolean,
            home_points integer, away_points integer
        )
    """)
    # g_upcoming tips at 23:30 UTC = 7:30 PM Eastern (EDT); g_tbd has no time.
    con.execute("""
        insert into predictions values
            ('p1', 'ridge-v1', '2026-09-20 12:00:00', 'g_upcoming', '2026-27',
             '2026-10-21', 1610612738, 1610612747, 3.5, 0.61),
            ('p4', 'ridge-v1', '2026-09-20 12:00:00', 'g_tbd', '2026-27',
             '2026-10-22', 1610612738, 1610612747, -2.2, 0.41)
    """)
    con.execute("""
        insert into main_staging.stg_schedule values
            ('g_upcoming', '2026-10-21', '2026-10-21 23:30:00', 'BOS', 'NYK', 1),
            ('g_tbd', '2026-10-22', null, 'PHI', 'LAL', 1)
    """)
    if settled:
        con.execute("""
            insert into predictions values
                ('p2', 'ridge-v1', '2026-09-01 12:00:00', 'g_settled', '2026-27',
                 '2026-09-05', 1610612738, 1610612747, 4.0, 0.63),
                ('p3', 'ridge-v1', '2026-09-01 12:00:00', 'g_no_contest', '2026-27',
                 '2026-09-06', 1610612738, 1610612747, 4.0, 0.63)
        """)
        con.execute("""
            insert into main_staging.stg_schedule values
                ('g_settled', '2026-09-05', '2026-09-05 23:00:00', 'BOS', 'NYK', 3),
                ('g_no_contest', '2026-09-06', '2026-09-06 23:00:00', 'BOS', 'NYK', 3)
        """)
        # g_no_contest is the shape the one real cancelled game in the
        # warehouse takes: a 0-0 "final" that never happened. A prediction
        # exists for it (p3), so if the settled-predictions join ever loses
        # its exclusion, it gets graded as a definite miss on a 0 margin.
        con.execute("""
            insert into main_marts.fct_team_game values
                ('g_settled', 5.0, true, 110, 105),
                ('g_no_contest', 0.0, false, 0, 0)
        """)
    con.close()


def _point_db_at(path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DB_PATH", path)
    _reset_cache()


@pytest.fixture
def no_predictions_db(tmp_path, monkeypatch):
    """A warehouse with no `predictions` table at all."""
    path = tmp_path / "no_predictions.duckdb"
    duckdb.connect(str(path)).close()
    _point_db_at(path, monkeypatch)
    yield path
    _reset_cache()


@pytest.fixture
def with_predictions_db(tmp_path, monkeypatch):
    """Upcoming games plus one settled prediction and one no-contest game."""
    path = tmp_path / "with_predictions.duckdb"
    _build_warehouse(path, settled=True)
    _point_db_at(path, monkeypatch)
    yield path
    _reset_cache()


@pytest.fixture
def upcoming_only_db(tmp_path, monkeypatch):
    """Predictions exist for future games but nothing has settled yet."""
    path = tmp_path / "upcoming_only.duckdb"
    _build_warehouse(path, settled=False)
    _point_db_at(path, monkeypatch)
    yield path
    _reset_cache()


def _page_text(at) -> str:
    return " ".join(md.value for md in at.get("markdown"))


def test_renders_without_exception_when_predictions_exist(with_predictions_db):
    at = AppTest.from_string(SCRIPT)
    at.run()
    assert not at.exception
    # The one grid on the page is the recent-results table; upcoming games
    # are cards, not a dataframe.
    assert len(at.get("dataframe")) == 1
    # Asserting only the dataframe count above would still pass if
    # prediction_track_record() silently returned {"n": 0} and the page fell
    # back to the "nothing settled" st.info - that branch renders zero
    # dataframes. Check the KPI markdown actually rendered, so this test can
    # tell the two branches apart.
    assert "Accuracy" in _page_text(at), (
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


def test_upcoming_only_state_renders_with_no_settled_games(upcoming_only_db):
    at = AppTest.from_string(SCRIPT)
    at.run()
    assert not at.exception
    assert len(at.get("dataframe")) == 0
    infos = " ".join(i.value for i in at.info)
    assert "The first predictions settle after opening night (Wed, Oct 21)" in infos
    assert "Accuracy" not in _page_text(at)


def test_cards_show_eastern_tipoff_and_tbd(with_predictions_db):
    at = AppTest.from_string(SCRIPT)
    at.run()
    assert not at.exception
    text = _page_text(at)
    assert "7:30 PM ET" in text
    assert "TBD" in text
    # grouped under a date heading
    assert "#### Wed, Oct 21" in text
    assert "#### Thu, Oct 22" in text
    assert "bip-game" in text


def test_verdict_line_format_and_favorite(with_predictions_db):
    at = AppTest.from_string(SCRIPT)
    at.run()
    text = _page_text(at)
    verdicts = re.findall(r"[A-Z]{3} by \d+ · \d+%", text)
    assert len(verdicts) == 2
    # home 61% / margin 3.5 -> BOS by 4; home 41% -> the away team LAL is favored
    assert "BOS by 4 · 61%" in text
    assert "LAL by 2 · 59%" in text
    # probability bar labels on both sides
    assert "NYK 39%" in text and "BOS 61%" in text


def test_no_raw_column_names_in_any_grid(with_predictions_db):
    at = AppTest.from_string(SCRIPT)
    at.run()
    assert len(at.dataframe) >= 1
    for i in range(len(at.dataframe)):
        for col in at.dataframe[i].value.columns:
            assert "_" not in str(col), f"raw column name leaked: {col}"
    assert "win_probability" not in _page_text(at)


def test_recent_results_grid_shows_check_or_cross(with_predictions_db):
    at = AppTest.from_string(SCRIPT)
    at.run()
    grid = at.dataframe[0].value
    assert list(grid.columns) == ["Date", "Matchup", "Pick", "Final", "Correct"]
    row = grid.iloc[0]
    assert row["Matchup"] == "NYK @ BOS"
    assert row["Pick"] == "BOS 63%"
    assert row["Final"] == "BOS 110-105"
    assert row["Correct"] in ("✓", "✗")
    assert row["Correct"] == "✓"
    # the no-contest game is not listed
    assert len(grid) == 1


def test_calibration_bins_empty_below_fifty_settled_games(with_predictions_db):
    out = db.calibration_bins()
    assert out.empty
    assert list(out.columns) == ["bin_mid", "predicted_mean", "actual_rate", "n"]


def test_recent_settled_predictions_shape(with_predictions_db):
    out = db.recent_settled_predictions()
    assert list(out.columns) == ["game_date", "home", "away", "home_pts",
                                 "away_pts", "win_probability",
                                 "predicted_margin", "correct"]
    assert len(out) == 1
    assert bool(out.iloc[0]["correct"]) is True


def test_upcoming_predictions_carries_tipoff(with_predictions_db):
    out = db.upcoming_predictions()
    assert "tipoff_utc" in out.columns
    assert out["tipoff_utc"].isna().sum() == 1


def test_calibration_bins_math_on_sixty_synthetic_games(tmp_path, monkeypatch):
    rng = np.random.default_rng(7)
    path = tmp_path / "sixty.duckdb"
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
        create table main_marts.fct_team_game (
            game_id varchar, margin double, home_won boolean,
            home_points integer, away_points integer
        )
    """)
    probs = rng.uniform(0.02, 0.98, 60)
    for i, p in enumerate(probs):
        won = bool(rng.uniform() < p)
        con.execute(
            "insert into predictions values (?, 'ridge-v1', '2026-01-01 00:00:00', "
            "?, '2025-26', '2026-01-02', 1, 2, ?, ?)",
            [f"p{i}", f"g{i}", float((p - 0.5) * 20), float(p)])
        con.execute(
            "insert into main_marts.fct_team_game values (?, ?, ?, 110, 100)",
            [f"g{i}", 10.0 if won else -10.0, won])
    con.close()
    _point_db_at(path, monkeypatch)
    try:
        out = db.calibration_bins()
        assert int(out["n"].sum()) == 60
        assert out["actual_rate"].between(0, 1).all()
        assert out["predicted_mean"].between(0, 1).all()
        assert out["bin_mid"].between(0, 1).all()
        assert len(out) <= 10 and (out["n"] > 0).all()
    finally:
        _reset_cache()
