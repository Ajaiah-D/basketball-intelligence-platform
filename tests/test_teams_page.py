"""The Teams page's Team tab (dashboard/views/teams/), rendered with AppTest.

Runs against the real warehouse via the `con` fixture, like
test_players_page.py, and against a copy of it without the diagnosis marts
for the fallback an older published warehouse gets.
"""

import json
import shutil

import duckdb
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from core import paths
from dashboard.lib import diagnosis, nav
from dashboard.lib.data import core as data_core
from dashboard.lib.data import diagnosis as diagnosis_data
from dashboard.lib.data import seasons
from dashboard.lib.state import PLAYERS_PICK_KEY, SEASON_KEY
from dashboard.views.teams import breakdown, scatter

SCRIPT = """
from dashboard.views import teams
teams.render()
"""

# The fixture warehouse's seasons: 2024-25 is modern (every rank), 1979-80
# predates the inputs (no rank at all). The full warehouse has both too.
MODERN = "2024-25"
EARLY = "1979-80"


def _app(season: str, team_name: str | None = None) -> AppTest:
    at = AppTest.from_string(SCRIPT, default_timeout=60)
    at.session_state["season"] = season
    at.run()
    assert not at.exception, at.exception
    if team_name is not None:
        at.selectbox[0].select(team_name).run()
        assert not at.exception, at.exception
    return at


def _text(at: AppTest) -> str:
    return " ".join(m.value for m in at.markdown)


def _captions(at: AppTest) -> str:
    return " ".join(c.value for c in at.caption)


def _team_names(con, season: str) -> tuple[str, str]:
    """The (best, worst) team by net rating rank that season."""
    rows = con.execute(
        """
        select s.team_name
        from main_marts.mart_team_profile p
        join main_marts.mart_team_standings s
          on s.season = p.season and s.team_id = p.team_id
        where p.season = ? and p.net_rating_rank is not null
        order by p.net_rating_rank, s.team_name
        """,
        [season],
    ).fetchall()
    assert rows, f"no ranked teams in {season}"
    return rows[0][0], rows[-1][0]


@pytest.mark.parametrize("which", [0, 1], ids=["strongest", "weakest"])
def test_team_tab_shows_the_profile(con, which):
    assert MODERN in seasons.seasons()
    team = _team_names(con, MODERN)[which]
    at = _app(MODERN, team)
    text = _text(at)
    assert "How they rank in the league" in text
    assert "Four Factors" not in text
    # Evidence, not a verdict: no "Best at / Worst at" line.
    assert "Best at" not in _captions(at)
    assert not at.info
    charts = at.get("plotly_chart")
    # The profile, the player breakdown, the margins and the two-stat
    # scatter.
    assert len(charts) == 4


def test_an_early_season_has_no_profile_and_no_error(con):
    assert EARLY in seasons.seasons()
    at = _app(EARLY)
    assert "How they rank in the league" not in _text(at)
    assert not at.info
    assert not at.exception
    # The breakdown still shows the rotation where the box scores allow.
    assert "Player breakdown" in _text(at)


@pytest.fixture
def warehouse_without_profile(con, tmp_path):
    """A copy of the real warehouse as published before the diagnosis marts.
    It keeps the file name: dbt's views name the catalog, which DuckDB
    takes from the file name."""
    real = paths.warehouse_path()
    path = tmp_path / real.name
    shutil.copyfile(real, path)
    copy = duckdb.connect(str(path))
    copy.execute("drop table main_marts.mart_team_profile")
    copy.execute("drop table main_marts.mart_player_percentiles")
    copy.execute("drop table main_marts.mart_player_defense")
    copy.close()
    with data_core.use_warehouse(path):
        yield path


def test_without_the_marts_the_four_factors_show_with_one_notice(warehouse_without_profile):
    assert not diagnosis_data.profile_available()
    at = _app(MODERN)
    assert len(at.info) == 1
    assert "next data refresh" in at.info[0].value
    text = _text(at)
    assert "Four Factors" in text
    assert "How they rank in the league" not in text
    # No second notice for the breakdown: the one line covers both.
    assert "Player breakdown" not in text


# --- The player breakdown ---------------------------------------------------------

VERDICT_WORDS = ("strength", "weakness", "drives", "best", "worst", "most of")


def _area(at: AppTest, label: str) -> AppTest:
    at.selectbox(key=breakdown.AREA_KEY).select(label).run()
    assert not at.exception, at.exception
    return at


def test_the_breakdown_defaults_to_the_first_area(con):
    team = _team_names(con, MODERN)[0]
    at = _app(MODERN, team)
    assert "Player breakdown" in _text(at)
    assert at.selectbox(key=breakdown.AREA_KEY).value == diagnosis.AREAS[0].label
    # The team's rank in the area, as a plain chip.
    assert "Team: #" in _text(at)


# The section on its own, so the verdict check reads only its text.
BREAKDOWN_SCRIPT = """
import streamlit as st
from dashboard.views.teams.breakdown import render_breakdown
render_breakdown(st.session_state["season"], st.session_state["team"])
"""


def _team_code(con, team_name: str) -> str:
    row = con.execute(
        "select team_abbreviation from main_marts.mart_team_standings"
        " where season = ? and team_name = ?",
        [MODERN, team_name],
    ).fetchone()
    assert row
    return row[0]


@pytest.mark.parametrize("area", diagnosis.AREAS, ids=[a.key for a in diagnosis.AREAS])
def test_every_area_shows_evidence_and_no_verdict(con, area):
    team = _team_code(con, _team_names(con, MODERN)[0])
    at = AppTest.from_string(BREAKDOWN_SCRIPT, default_timeout=60)
    at.session_state["season"] = MODERN
    at.session_state["team"] = team
    at.run()
    assert not at.exception, at.exception
    at = _area(at, area.label)
    captions = _captions(at)
    text = _text(at)
    assert "Team: #" in text
    assert area.caption in captions
    if area.defensive:
        assert "film" in captions
    assert len(at.get("plotly_chart")) == 1
    # The numbers table names the league median under the measures.
    assert "League median" in text
    shown = (captions + " " + text).lower()
    for word in VERDICT_WORDS:
        assert word not in shown, word


def test_on_off_before_1996_is_not_available_without_error(con):
    assert EARLY in seasons.seasons()
    at = _area(_app(EARLY), "Defense on/off (estimate)")
    assert "needs 500+ minutes with one team, from 1996-97" in _captions(at)


@pytest.fixture
def switched(monkeypatch):
    """nav.go without a running app: a registered stand-in page and a
    switch_page that records where it was sent."""
    sent: list = []
    monkeypatch.setattr(nav, "_PAGES", {"players": "players-page"})
    monkeypatch.setattr(st, "switch_page", sent.append)
    return sent


def test_open_on_players_presets_the_player_and_switches(con, switched):
    team = _team_names(con, MODERN)[0]
    at = _app(MODERN, team)
    picker = at.selectbox(key=breakdown.OPEN_KEY)
    player = picker.options[1]
    picker.select(player).run()
    at.button(key=f"{breakdown.OPEN_KEY}_go").click().run()
    assert not at.exception, at.exception
    assert at.session_state[PLAYERS_PICK_KEY] == player
    assert at.session_state[SEASON_KEY] == MODERN
    assert switched == ["players-page"]


def test_a_short_rotation_gets_one_button_per_player(con, switched, monkeypatch):
    monkeypatch.setattr(breakdown, "MAX_BUTTONS", 100)
    team = _team_names(con, MODERN)[0]
    at = _app(MODERN, team)
    buttons = [b for b in at.button if str(b.key).startswith(f"{breakdown.OPEN_KEY}_")]
    assert len(buttons) > 1
    player = buttons[0].label
    buttons[0].click().run()
    assert not at.exception, at.exception
    assert at.session_state[PLAYERS_PICK_KEY] == player
    assert switched == ["players-page"]


# --- The two-stat scatter -------------------------------------------------------------


def _figures(at: AppTest) -> list[dict]:
    return [json.loads(c.proto.spec) for c in at.get("plotly_chart")]


def _scatter_figure(at: AppTest) -> dict:
    """The scatter: the figure whose dashed shapes are league-average lines."""
    found = [
        f
        for f in _figures(at)
        if f["layout"].get("shapes") and f["data"][0].get("mode") == "markers+text"
    ]
    assert len(found) == 1
    return found[0]


def test_the_scatter_defaults_to_offense_against_defense(con):
    team = _team_names(con, MODERN)[0]
    at = _app(MODERN, team)
    assert at.selectbox(key=scatter.X_KEY).value == "offensive_rating"
    assert at.selectbox(key=scatter.Y_KEY).value == "defensive_rating"
    fig = _scatter_figure(at)
    assert fig["layout"]["xaxis"]["title"]["text"] == "Offensive rating"
    # Up is the better defence, and the axis says so.
    assert fig["layout"]["yaxis"]["autorange"] == "reversed"
    assert "reversed" in fig["layout"]["yaxis"]["title"]["text"]
    # All 30 teams, the picked one as a trace of its own.
    assert sum(len(t["x"]) for t in fig["data"]) == 30
    assert len(fig["data"][1]["x"]) == 1


def test_the_scatter_takes_any_other_pair(con):
    team = _team_names(con, MODERN)[0]
    at = _app(MODERN, team)
    at.selectbox(key=scatter.X_KEY).select("effective_fg_pct").run()
    at.selectbox(key=scatter.Y_KEY).select("pace").run()
    assert not at.exception, at.exception
    assert not at.info
    fig = _scatter_figure(at)
    assert fig["layout"]["xaxis"]["title"]["text"] == "eFG%"
    assert fig["layout"]["yaxis"]["title"]["text"] == "Pace"
    # Neither is lower-is-better, so neither axis is reversed.
    assert fig["layout"]["yaxis"].get("autorange") != "reversed"
    assert fig["layout"]["xaxis"].get("autorange") != "reversed"
    hover = fig["data"][0]["hovertext"][0]
    assert "eFG%" in hover and "Pace" in hover and " of 30)" in hover
    # The choice survives picking another team.
    at.selectbox[0].select(_team_names(con, MODERN)[1]).run()
    assert not at.exception, at.exception
    assert at.selectbox(key=scatter.X_KEY).value == "effective_fg_pct"


def test_a_lower_is_better_stat_is_reversed_wherever_it_sits(con):
    team = _team_names(con, MODERN)[0]
    at = _app(MODERN, team)
    at.selectbox(key=scatter.X_KEY).select("turnover_pct").run()
    assert not at.exception, at.exception
    fig = _scatter_figure(at)
    assert fig["layout"]["xaxis"]["autorange"] == "reversed"
    assert "reversed" in fig["layout"]["xaxis"]["title"]["text"]


def test_the_scatter_in_an_early_season_is_left_out(con):
    at = _app(EARLY)
    assert not at.exception
    # Too few stats that season: no section and no pickers, rather than an
    # empty chart.
    assert "Compare two stats" not in _text(at)
    keys = {s.key for s in at.selectbox}
    assert scatter.X_KEY not in keys and scatter.Y_KEY not in keys


def test_without_the_marts_the_scatter_falls_back_to_the_ratings(warehouse_without_profile):
    at = _app(MODERN)
    assert not at.exception
    assert len(at.selectbox) == 1  # only the team picker
    assert len(at.info) == 1  # the profile's notice, not another
    fig = _scatter_figure(at)
    assert fig["layout"]["yaxis"]["autorange"] == "reversed"
