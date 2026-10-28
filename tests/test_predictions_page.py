"""dashboard/views/predictions.py, rendered with AppTest in every warehouse
state a real deploy can be in: predictions published and settled,
published but nothing settled yet, none published yet (a warehouse built
before ml/predict.py ever ran), and one published before
mart_settled_predictions existed.

"Today" is injected (monkeypatching page.today), so nothing here depends
on the date the tests run.
"""

import re
from datetime import date

import duckdb
import numpy as np
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from dashboard.lib import nav, stats
from dashboard.lib import theme as T
from dashboard.lib.data import core as data_core
from dashboard.lib.data import predictions
from dashboard.views import predictions as page

SCRIPT = """
from dashboard.views import predictions
predictions.render()
"""


def _build_warehouse(path, add_mart, settled: bool = True) -> None:
    """Write a small warehouse: two upcoming games (one with a tip-off time,
    one without) and, when `settled`, a graded game plus a no-contest.
    `add_mart` is conftest's add_settled_mart, or None for a warehouse
    published before mart_settled_predictions existed."""
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
    if add_mart is not None:
        add_mart(con)
    con.close()


@pytest.fixture
def no_predictions_db(tmp_path):
    """A warehouse with no `predictions` table at all."""
    path = tmp_path / "no_predictions.duckdb"
    duckdb.connect(str(path)).close()
    with data_core.use_warehouse(path):
        yield path


@pytest.fixture
def with_predictions_db(tmp_path, add_settled_mart):
    """Upcoming games plus one settled prediction and one no-contest game."""
    path = tmp_path / "with_predictions.duckdb"
    _build_warehouse(path, add_settled_mart, settled=True)
    with data_core.use_warehouse(path):
        yield path


@pytest.fixture
def upcoming_only_db(tmp_path, add_settled_mart):
    """Predictions exist for future games but nothing has settled yet."""
    path = tmp_path / "upcoming_only.duckdb"
    _build_warehouse(path, add_settled_mart, settled=False)
    with data_core.use_warehouse(path):
        yield path


# The base warehouse's upcoming games are on Oct 21 and 22.
OPENING = date(2026, 10, 21)


def _run(monkeypatch, today: date = OPENING) -> AppTest:
    monkeypatch.setattr(page, "today", lambda: today)
    at = AppTest.from_string(SCRIPT, default_timeout=30)
    at.run()
    assert not at.exception
    return at


def _page_text(at) -> str:
    return " ".join(md.value for md in at.get("markdown"))


def _infos(at) -> list[str]:
    return [i.value for i in at.info]


def _tables(at, css: str) -> list[str]:
    """The HTML of each markdown block wrapped in `css` (bip-upcoming or
    bip-recent)."""
    return [md.value for md in at.markdown if f'class="{css}"' in md.value]


def _header(table: str) -> list[str]:
    head = re.search(r"<tr>(.*?)</tr>", table).group(1)
    return [_plain(c) for c in re.findall(r"<th[^>]*>(.*?)</th>", head)]


def _rows(table: str) -> list[list[str]]:
    """Each body row as its cells' raw HTML."""
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", table)[1:]
    return [re.findall(r"<td[^>]*>(.*?)</td>", r) for r in rows]


def _plain(cell: str) -> str:
    # The glossary tip's "i" is a span of its own: drop it with its tags.
    cell = re.sub(r'<span class="bip-tip".*?</span>', "", cell)
    return re.sub(r"<[^>]+>", "", cell).strip()


# --- Upcoming games ------------------------------------------------------------


def test_renders_with_predictions_and_a_track_record(with_predictions_db, monkeypatch):
    at = _run(monkeypatch)
    # Every table on the page is site-styled HTML, none a native grid.
    assert len(at.get("dataframe")) == 0
    # The KPI branch rendered, not the "nothing settled" notice.
    text = _page_text(at)
    assert "Accuracy" in text and "Brier score" in text and "Margin error" in text
    assert "Settled games: 1" in " ".join(c.value for c in at.caption)


def test_each_day_is_one_table_under_its_date(with_predictions_db, monkeypatch):
    at = _run(monkeypatch)
    tables = _tables(at, "bip-upcoming")
    assert [_header(t)[0] for t in tables] == ["Wed, Oct 21", "Thu, Oct 22"]
    assert [_header(t)[1:] for t in tables] == [["Matchup", "Chance", "Margin"]] * 2
    assert [len(_rows(t)) for t in tables] == [1, 1]
    # The Eastern tip-off, and TBD for the game without one.
    assert _plain(_rows(tables[0])[0][0]) == "7:30 PM ET"
    assert _plain(_rows(tables[1])[0][0]) == "TBD"


def test_a_row_is_tipoff_matchup_chance_and_margin(with_predictions_db, monkeypatch):
    at = _run(monkeypatch)
    first, second = (_rows(t)[0] for t in _tables(at, "bip-upcoming"))
    # home 61%, margin 3.5: BOS is bold in its colour, by 4.
    assert [_plain(c) for c in first] == ["7:30 PM ET", "NYK @ BOS", "61%", "by 4"]
    assert f'<b style="color:{T.team_color("BOS")}">BOS</b>' in first[1]
    assert f"background:{T.team_color('BOS')}" in first[2]
    # home 41%: the away team LAL is the favourite, at 59%.
    assert [_plain(c) for c in second] == ["TBD", "LAL @ PHI", "59%", "by 2"]
    assert f'<b style="color:{T.team_color("LAL")}">LAL</b>' in second[1]


@pytest.fixture
def week_db(tmp_path, add_settled_mart):
    """The base warehouse plus a week of upcoming games around Oct 24: one
    left over from the day before (no result yet), three on the 24th, one
    each on the 26th and the 30th, and one on the 31st, a day past the
    7-day window."""
    path = tmp_path / "week.duckdb"
    _build_warehouse(path, add_settled_mart, settled=True)
    games = [
        # game_id, day, tip-off (UTC), home, away, home win probability, margin
        ("w_left", "2026-10-23", "2026-10-23 23:00:00", "MIA", "ORL", 0.60, 3.0),
        ("w_a", "2026-10-24", "2026-10-24 23:00:00", "BOS", "NYK", 0.65, 5.2),
        ("w_b", "2026-10-24", "2026-10-25 02:00:00", "DEN", "LAL", 0.30, -6.4),
        ("w_c", "2026-10-24", "2026-10-24 23:30:00", "CHI", "DET", 0.53, 0.3),
        ("w_d", "2026-10-26", "2026-10-26 23:00:00", "GSW", "SAC", 0.71, 7.0),
        ("w_e", "2026-10-30", "2026-10-30 23:00:00", "PHX", "UTA", 0.58, 2.0),
        ("w_out", "2026-10-31", "2026-10-31 23:00:00", "SAS", "HOU", 0.62, 3.0),
    ]
    con = duckdb.connect(str(path))
    for gid, day, tip, home, away, prob, margin in games:
        con.execute(
            "insert into predictions values (?, 'ridge-v1', '2026-10-20 12:00:00', ?, "
            "'2026-27', ?, 1, 2, ?, ?)",
            [f"p_{gid}", gid, day, margin, prob],
        )
        con.execute(
            "insert into main_staging.stg_schedule values (?, ?, ?, ?, ?, 1)",
            [gid, day, tip, home, away],
        )
    con.close()
    with data_core.use_warehouse(path):
        yield path


def test_the_next_seven_days_one_table_a_day(week_db, monkeypatch):
    at = _run(monkeypatch, today=date(2026, 10, 24))
    tables = _tables(at, "bip-upcoming")
    # The 23rd's game has no result but is not upcoming; the 31st is past
    # the window.
    assert [_header(t)[0] for t in tables] == ["Sat, Oct 24", "Mon, Oct 26", "Fri, Oct 30"]
    assert [len(_rows(t)) for t in tables] == [3, 1, 1]
    # Within a day, by tip-off: 7:00, 7:30, then 10:00 PM.
    assert [_plain(r[0]) for r in _rows(tables[0])] == ["7:00 PM ET", "7:30 PM ET", "10:00 PM ET"]


def test_no_value_appears_twice_in_a_row(week_db, monkeypatch):
    at = _run(monkeypatch, today=date(2026, 10, 24))
    for table in _tables(at, "bip-upcoming"):
        for row in _rows(table):
            text = " ".join(_plain(c) for c in row)
            teams = re.findall(r"\b[A-Z]{3}\b", text)
            assert len(teams) == len(set(teams)) == 2, text
            assert text.count("%") == 1, text
            # The favourite is marked once at most, in the matchup only.
            assert row[1].count("<b") <= 1
            assert "<b" not in row[0] + row[2] + row[3]


def test_under_55_percent_reads_toss_up_with_no_team_marked(week_db, monkeypatch):
    at = _run(monkeypatch, today=date(2026, 10, 24))
    rows = _rows(_tables(at, "bip-upcoming")[0])
    toss = next(r for r in rows if "DET @ CHI" in _plain(r[1]))
    assert [_plain(c) for c in toss] == ["7:30 PM ET", "DET @ CHI", "53%toss-up", "by 1"]
    assert "<b" not in toss[1]
    assert "background:" not in toss[2]
    others = [r for r in rows if r is not toss]
    assert all("toss-up" not in r[2] for r in others)


def test_no_games_in_the_next_seven_days_is_one_line(with_predictions_db, monkeypatch):
    at = _run(monkeypatch, today=date(2026, 12, 1))
    assert _tables(at, "bip-upcoming") == []
    assert "No games in the next 7 days." in _infos(at)


def test_the_schedule_link_opens_the_schedule_page(with_predictions_db, monkeypatch):
    sent: list[str] = []
    monkeypatch.setattr(nav, "go", sent.append)
    at = _run(monkeypatch)
    link = next(b for b in at.button if "Schedule" in b.label)
    link.click().run()
    assert sent == ["schedule"]


# --- Track record --------------------------------------------------------------


def test_no_contest_game_is_not_scored_against_the_track_record(with_predictions_db):
    """A cancelled game recorded as a 0-0 final must not be graded.

    The fixture has two settled predictions, one of them for g_no_contest.
    Only g_settled is a real result, so n must be 1. Without the
    exclusion n is 2 and the extra row is scored as a miss (the model said
    home by 4, the "actual" margin is 0 and home_won is false), which drags
    accuracy to 0.5 and inflates Brier on a game that was never played.
    """
    record = predictions.prediction_track_record()
    assert record["n"] == 1, (
        "g_no_contest (0-0, cancelled) was scored; the settled-predictions "
        "mart is missing its no-contest exclusion"
    )
    assert record["accuracy"] == 1.0


def test_renders_without_exception_when_predictions_table_is_absent(no_predictions_db, monkeypatch):
    at = _run(monkeypatch)
    assert _infos(at) == [
        "No predictions have been published yet. They are written once a "
        "week, before the games are played."
    ]


def test_nothing_settled_yet_is_one_line(upcoming_only_db, monkeypatch):
    at = _run(monkeypatch)
    assert _infos(at) == ["The first predictions settle after opening night (Wed, Oct 21)."]
    assert "Accuracy" not in _page_text(at)
    assert _tables(at, "bip-recent") == []
    # The upcoming games still show.
    assert len(_tables(at, "bip-upcoming")) == 2


def test_nothing_settled_and_nothing_upcoming(upcoming_only_db, monkeypatch):
    at = _run(monkeypatch, today=date(2026, 12, 1))
    assert _infos(at) == [
        "No games in the next 7 days.",
        "No predictions have been settled yet. Check back after the first games are played.",
    ]


@pytest.fixture
def no_mart_db(tmp_path):
    """Predictions and results, but published before mart_settled_predictions."""
    path = tmp_path / "no_mart.duckdb"
    _build_warehouse(path, None, settled=True)
    with data_core.use_warehouse(path):
        yield path


def test_a_warehouse_without_the_mart_still_lists_upcoming_games(no_mart_db, monkeypatch):
    at = _run(monkeypatch)
    assert _infos(at) == ["The track record appears after the next data refresh."]
    assert "Accuracy" not in _page_text(at)
    assert _tables(at, "bip-recent") == []
    assert len(_tables(at, "bip-upcoming")) == 2


# --- Details and recent results --------------------------------------------------

DETAILS = "How the model works and how well-calibrated it is"


def test_the_details_expander_holds_the_explainer_without_a_chart_below_fifty(
    with_predictions_db, monkeypatch
):
    at = _run(monkeypatch)
    assert [e.label for e in at.expander] == [DETAILS]
    details = at.expander[0]
    assert "Elo rating" in " ".join(md.value for md in details.markdown)
    assert len(details.get("plotly_chart")) == 0


def test_the_details_expander_holds_calibration_with_fifty_settled(sixty_settled_db, monkeypatch):
    at = _run(monkeypatch)
    details = at.expander[0]
    assert details.label == DETAILS
    assert len(details.get("plotly_chart")) == 1
    assert "Calibration" in " ".join(md.value for md in details.markdown)
    # The page's only chart is the one in the expander.
    assert len(at.get("plotly_chart")) == 1


def test_recent_results_is_a_compact_table(with_predictions_db, monkeypatch):
    at = _run(monkeypatch)
    (table,) = _tables(at, "bip-recent")
    assert _header(table) == ["Matchup", "Pick", "Chance", "Final", "Correct"]
    rows = _rows(table)
    # The no-contest game is not listed.
    assert [[_plain(c) for c in r] for r in rows] == [
        ["NYK @ BOS", "BOS", "63%", "BOS 110-105", "✓"]
    ]


def test_recent_results_show_the_ten_latest(sixty_settled_db, monkeypatch):
    at = _run(monkeypatch)
    (table,) = _tables(at, "bip-recent")
    assert len(_rows(table)) == 10


def test_a_coin_flip_counts_as_a_home_pick_everywhere(coin_flip_db, monkeypatch):
    # A 50% game is a home pick in the recent results, so the headline
    # accuracy must grade it the same way.
    record = predictions.prediction_track_record()
    assert record["n"] == 1
    assert record["accuracy"] == 1.0
    recent = predictions.recent_settled_predictions()
    assert bool(recent.iloc[0]["correct"]) is True
    at = _run(monkeypatch)
    (table,) = _tables(at, "bip-recent")
    assert [_plain(c) for c in _rows(table)[0]][1:3] == ["BOS", "50%"]
    assert _plain(_rows(table)[0][4]) == "✓"


def test_no_raw_column_names_on_the_page(with_predictions_db, monkeypatch):
    at = _run(monkeypatch)
    text = _page_text(at)
    for raw in ("win_probability", "predicted_margin", "home_pts", "tipoff_utc"):
        assert raw not in text


# --- Data layer and helpers ------------------------------------------------------


def test_calibration_bins_empty_below_fifty_settled_games(with_predictions_db):
    out = stats.calibration_bins(predictions.settled_predictions())
    assert out.empty
    assert list(out.columns) == ["bin_mid", "predicted_mean", "actual_rate", "n"]


def test_recent_settled_predictions_shape(with_predictions_db):
    out = predictions.recent_settled_predictions()
    assert list(out.columns) == [
        "game_date",
        "home",
        "away",
        "home_pts",
        "away_pts",
        "win_probability",
        "predicted_margin",
        "correct",
    ]
    assert len(out) == 1
    assert bool(out.iloc[0]["correct"]) is True


def test_upcoming_predictions_covers_the_days_asked_for(with_predictions_db):
    out = predictions.upcoming_predictions(date(2026, 10, 21), date(2026, 10, 27))
    assert "tipoff_utc" in out.columns
    assert out["game_id"].tolist() == ["g_upcoming", "g_tbd"]
    assert out["tipoff_utc"].isna().sum() == 1
    one_day = predictions.upcoming_predictions(date(2026, 10, 22), date(2026, 10, 22))
    assert one_day["game_id"].tolist() == ["g_tbd"]


def test_a_tipoff_after_midnight_utc_groups_under_the_eastern_date():
    frame = pd.DataFrame(
        {
            "game_id": ["late"],
            "game_date": ["2026-10-22"],
            # 02:00 UTC on the 22nd is 10:00 PM Eastern on the 21st
            "tipoff_utc": [pd.Timestamp("2026-10-22 02:00:00")],
            "win_probability": [0.55],
            "predicted_margin": [1.5],
            "home_team_abbreviation": ["BOS"],
            "away_team_abbreviation": ["NYK"],
        }
    )
    out = page._upcoming(frame)
    assert out.iloc[0]["day_et"] == date(2026, 10, 21)
    assert out.iloc[0]["tip_label"] == "10:00 PM ET"


def test_calibration_bins_math_on_sixty_synthetic_games(tmp_path, add_settled_mart):
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
            [f"p{i}", f"g{i}", float((p - 0.5) * 20), float(p)],
        )
        con.execute(
            "insert into main_marts.fct_team_game values (?, ?, ?, 110, 100)",
            [f"g{i}", 10.0 if won else -10.0, won],
        )
    add_settled_mart(con)
    con.close()
    with data_core.use_warehouse(path):
        out = stats.calibration_bins(predictions.settled_predictions())
    assert int(out["n"].sum()) == 60
    assert out["actual_rate"].between(0, 1).all()
    assert out["predicted_mean"].between(0, 1).all()
    assert out["bin_mid"].between(0, 1).all()
    assert len(out) <= 10 and (out["n"] > 0).all()


def _add_settled_games(path, probs, home_won) -> None:
    """Append graded games g_extra{i}: a prediction, a final schedule row and
    a result, one per (probability, home_won) pair."""
    con = duckdb.connect(str(path))
    for i, (p, won) in enumerate(zip(probs, home_won, strict=True)):
        gid = f"g_extra{i}"
        day = f"2026-08-{1 + i % 28:02d}"
        con.execute(
            "insert into predictions values (?, 'ridge-v1', '2026-07-01 12:00:00', "
            "?, '2025-26', ?, 1610612738, 1610612747, ?, ?)",
            [f"px{i}", gid, day, float((p - 0.5) * 20), float(p)],
        )
        con.execute(
            "insert into main_staging.stg_schedule values (?, ?, ?, 'BOS', 'NYK', 3)",
            [gid, day, f"{day} 23:00:00"],
        )
        con.execute(
            "insert into main_marts.fct_team_game values (?, ?, ?, ?, ?)",
            [gid, 6.0 if won else -6.0, bool(won), 106 if won else 100, 100 if won else 106],
        )
    con.close()


@pytest.fixture
def sixty_settled_db(tmp_path, add_settled_mart):
    """The standard warehouse plus 60 graded games: enough for calibration."""
    path = tmp_path / "sixty_settled.duckdb"
    _build_warehouse(path, add_settled_mart, settled=True)
    rng = np.random.default_rng(3)
    probs = rng.uniform(0.05, 0.95, 60)
    _add_settled_games(path, probs, rng.uniform(size=60) < probs)
    with data_core.use_warehouse(path):
        yield path


@pytest.fixture
def coin_flip_db(tmp_path, add_settled_mart):
    """One graded game the model called at exactly 50%, won by the home team."""
    path = tmp_path / "coin_flip.duckdb"
    _build_warehouse(path, add_settled_mart, settled=False)
    _add_settled_games(path, [0.5], [True])
    with data_core.use_warehouse(path):
        yield path
