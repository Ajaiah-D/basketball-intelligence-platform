"""Headless checks that dashboard/views/predictions.py never crashes, in
every warehouse state a real deploy can be in: predictions already
published and settled, published but nothing settled yet, and none published
yet (a warehouse built before ml/predict.py ever ran)."""

import re
from datetime import date

import duckdb
import numpy as np
import pandas as pd
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


def _add_settled_games(path, probs, home_won) -> None:
    """Append graded games g_extra{i}: a prediction, a final schedule row and
    a result, one per (probability, home_won) pair."""
    con = duckdb.connect(str(path))
    for i, (p, won) in enumerate(zip(probs, home_won)):
        gid = f"g_extra{i}"
        day = f"2026-08-{1 + i % 28:02d}"
        con.execute(
            "insert into predictions values (?, 'ridge-v1', '2026-07-01 12:00:00', "
            "?, '2025-26', ?, 1610612738, 1610612747, ?, ?)",
            [f"px{i}", gid, day, float((p - 0.5) * 20), float(p)])
        con.execute(
            "insert into main_staging.stg_schedule values "
            "(?, ?, ?, 'BOS', 'NYK', 3)", [gid, day, f"{day} 23:00:00"])
        con.execute(
            "insert into main_marts.fct_team_game values (?, ?, ?, ?, ?)",
            [gid, 6.0 if won else -6.0, bool(won), 106 if won else 100,
             100 if won else 106])
    con.close()


@pytest.fixture
def sixty_settled_db(tmp_path, monkeypatch):
    """The standard warehouse plus 60 graded games: enough for calibration."""
    path = tmp_path / "sixty_settled.duckdb"
    _build_warehouse(path, settled=True)
    rng = np.random.default_rng(3)
    probs = rng.uniform(0.05, 0.95, 60)
    _add_settled_games(path, probs, rng.uniform(size=60) < probs)
    _point_db_at(path, monkeypatch)
    yield path
    _reset_cache()


@pytest.fixture
def coin_flip_db(tmp_path, monkeypatch):
    """One graded game the model called at exactly 50%, won by the home team."""
    path = tmp_path / "coin_flip.duckdb"
    _build_warehouse(path, settled=False)
    _add_settled_games(path, [0.5], [True])
    _point_db_at(path, monkeypatch)
    yield path
    _reset_cache()


def _main_elements(at) -> list[tuple[str, str | None]]:
    """(type, markdown text or None) for every element in page order."""
    return [(el.type, el.value if el.type == "markdown" else None) for el in at.main]


def test_calibration_chart_renders_in_the_track_record_section(sixty_settled_db):
    at = AppTest.from_string(SCRIPT)
    at.run()
    assert not at.exception
    els = _main_elements(at)
    charts = [i for i, (t, _) in enumerate(els) if t == "plotly_chart"]
    assert len(charts) == 1

    def heading(prefix):
        return next(i for i, (t, v) in enumerate(els)
                    if t == "markdown" and v.startswith(prefix))

    # Track record > Calibration heading > the chart > Recent results heading
    assert (heading("#### Track record") < heading("#### Calibration")
            < charts[0] < heading("#### Recent results"))


def test_recent_results_grid_shows_every_row_without_scrolling(sixty_settled_db,
                                                               monkeypatch):
    import streamlit

    calls = []
    real = streamlit.dataframe

    def spy(data, *args, **kwargs):
        calls.append((len(data), kwargs))
        return real(data, *args, **kwargs)

    monkeypatch.setattr(streamlit, "dataframe", spy)
    at = AppTest.from_string(SCRIPT)
    at.run()
    assert not at.exception
    assert len(calls) == 1
    n, kwargs = calls[0]
    assert n == 20
    assert kwargs["height"] == 38 * (n + 1) + 3


def test_a_coin_flip_counts_as_a_home_pick_everywhere(coin_flip_db):
    # A 50% game is a home pick on the card and in the recent-results grid,
    # so the headline accuracy must grade it the same way.
    record = db.prediction_track_record()
    assert record["n"] == 1
    assert record["accuracy"] == 1.0
    recent = db.recent_settled_predictions()
    assert bool(recent.iloc[0]["correct"]) is True
    at = AppTest.from_string(SCRIPT)
    at.run()
    row = at.dataframe[0].value.iloc[0]
    assert row["Pick"] == "BOS 50%"
    assert row["Correct"] == "✓"


def test_a_tipoff_after_midnight_utc_groups_under_the_eastern_date():
    from dashboard.views import predictions

    frame = pd.DataFrame({
        "game_id": ["late"], "game_date": ["2026-10-22"],
        # 02:00 UTC on the 22nd is 10:00 PM Eastern on the 21st
        "tipoff_utc": [pd.Timestamp("2026-10-22 02:00:00")],
        "win_probability": [0.55], "predicted_margin": [1.5],
        "home_team_abbreviation": ["BOS"], "away_team_abbreviation": ["NYK"],
    })
    out = predictions._upcoming(frame)
    assert out.iloc[0]["day_et"] == date(2026, 10, 21)
    assert out.iloc[0]["tip_label"] == "10:00 PM ET"
