"""The Teams page (dashboard/views/teams/), rendered with AppTest: its three
tabs, the Team tab and the Team stats tab.

Runs against the real warehouse via the `con` fixture, like
test_players_page.py, and against a copy of it without the diagnosis marts
for the fallback an older published warehouse gets.
"""

import json
import shutil

import duckdb
import pandas as pd
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from core import paths
from dashboard.lib import diagnosis, nav
from dashboard.lib.data import advanced, seasons
from dashboard.lib.data import core as data_core
from dashboard.lib.data import diagnosis as diagnosis_data
from dashboard.lib.data import teams as team_data
from dashboard.lib.state import PLAYERS_PICK_KEY, SEASON_KEY
from dashboard.lib.widget_state import table_key
from dashboard.views.teams import breakdown, league, scatter
from dashboard.views.teams.common import TEAM_PICK_KEY, TEAMS_TAB_KEY

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


# A week into 2026-27 nobody has 10 games: the full warehouse only.
LIVE = "2026-27"
FULL = "2025-26"


@pytest.mark.full_warehouse
def test_early_in_a_season_the_breakdown_lowers_its_cut_and_says_so(con):
    assert seasons.seasons()[0] == LIVE
    cut = diagnosis_data.rotation_min_games(LIVE)
    assert cut < diagnosis_data.ROTATION_MIN_GAMES
    team = _team_names(con, LIVE)[0]
    at = _app(LIVE, team)
    assert "Player breakdown" in _text(at)
    assert f"Early in the season: players with {cut}+ games for the team." in _captions(at)
    assert at.selectbox(key=breakdown.OPEN_KEY).options


@pytest.mark.full_warehouse
def test_a_full_season_keeps_the_ten_game_rotation(con):
    assert diagnosis_data.rotation_min_games(FULL) == 10
    team = _team_names(con, FULL)[0]
    code = con.execute(
        "select team_abbreviation from main_marts.mart_team_standings"
        " where season = ? and team_name = ?",
        [FULL, team],
    ).fetchone()[0]
    assert (diagnosis_data.team_drivers(FULL, code)["games_played"] >= 10).all()
    at = _app(FULL, team)
    assert "Player breakdown" in _text(at)
    assert "Early in the season" not in _captions(at)


def test_a_team_without_a_rotation_gets_one_line(con):
    at = AppTest.from_string(BREAKDOWN_SCRIPT, default_timeout=60)
    at.session_state["season"] = MODERN
    at.session_state["team"] = "ZZZ"
    at.run()
    assert not at.exception, at.exception
    assert "Player breakdown" in _text(at)
    assert len(at.caption) == 1
    assert at.caption[0].value == "No ZZZ player has 10+ games for the team in 2024-25."
    assert not at.get("plotly_chart")


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


# --- The tabs and the Team stats tab ----------------------------------------------

# The sidebar box from dashboard/app.py, then the page, as test_players_page.py.
PAGE_SCRIPT = """
import streamlit as st
from dashboard.lib.data import seasons
from dashboard.views import teams
with st.sidebar:
    st.selectbox("Season", seasons.seasons(), key="season")
teams.render()
"""

# The Standings tab's caption: only there when that tab is drawn.
STANDINGS_NOTE = "Form shows the last five games, most recent on the right."

FOUR_FACTORS = [
    "effective_fg_pct",
    "turnover_pct",
    "offensive_rebound_pct",
    "free_throw_rate",
    "opp_effective_fg_pct",
    "opp_turnover_pct",
    "defensive_rebound_pct",
    "opp_free_throw_rate",
]


def _page(season: str, **state) -> AppTest:
    at = AppTest.from_string(PAGE_SCRIPT, default_timeout=60)
    at.session_state["season"] = season
    for key, value in state.items():
        at.session_state[key] = value
    at.run()
    assert not at.exception, at.exception
    return at


def _open(at: AppTest, label: str) -> AppTest:
    """Switch tabs the way the page itself does (lib.tabs.open_tab)."""
    at.session_state[f"{TEAMS_TAB_KEY}__next"] = label
    at.run()
    assert not at.exception, at.exception
    assert at.session_state[TEAMS_TAB_KEY] == label
    return at


def _columns(at: AppTest, label: str) -> AppTest:
    at.button_group(key=league.COLUMNS_KEY).set_value(label).run()
    assert not at.exception, at.exception
    return at


# The Team stats table has one key per column set (lib.widget_state.table_key).
TABLE_KEYS = {table_key(league.TABLE_KEY, s) for s in league.COLUMN_SETS}


def _table(at: AppTest):
    """The Team stats table, keyed for the column set on show."""
    assert at.dataframe(
        key=table_key(league.TABLE_KEY, at.button_group(key=league.COLUMNS_KEY).value)
    )
    (table,) = [d for d in at.dataframe if d.key in TABLE_KEYS]
    return table


def test_each_column_set_has_its_own_table_key():
    assert table_key(league.TABLE_KEY, "Four Factors") == "teams_table_four_factors"
    assert len(TABLE_KEYS) == len(league.COLUMN_SETS)


def test_the_page_has_three_tabs_and_opens_on_team(con):
    at = _page(MODERN)
    assert [t.label for t in at.tabs] == ["Team", "Team stats", "Standings"]
    assert at.session_state[TEAMS_TAB_KEY] == "Team"
    # Only the active tab is drawn: no Team stats table, no standings.
    assert not [d for d in at.dataframe if d.key in TABLE_KEYS]
    assert STANDINGS_NOTE not in _captions(at)


def test_team_stats_lists_every_team_by_net_rating(con):
    at = _page(MODERN, **{TEAMS_TAB_KEY: "Team stats"})
    shown = _table(at).value
    standings = team_data.standings(MODERN)
    assert len(shown) == len(standings)
    assert set(shown["team_name"]) == set(standings["team_name"])
    assert at.button_group(key=league.COLUMNS_KEY).value == "Basic"
    assert list(shown.columns) == ["team_name", "w", "l", "pct", "ppg", "opp_ppg", "net"]
    order = list(shown["team_name"])

    at = _columns(at, "Advanced")
    shown = _table(at).value
    assert list(shown["team_name"]) == order
    assert shown["net_rating"].is_monotonic_decreasing
    assert "Click a row to open that team." in _captions(at)
    assert "Ratings are NBA official." in _captions(at)


def test_team_stats_writes_pct_as_the_standings_do(con):
    at = _page(MODERN, **{TEAMS_TAB_KEY: "Team stats"})
    shown = _table(at).value
    standings = team_data.standings(MODERN).set_index("team_name")["pct"]
    # The fraction itself (0.780), not a percentage (78.0).
    assert list(shown["pct"]) == list(standings[shown["team_name"]])
    config = league._column_config(shown)["pct"]
    assert config["label"] == "PCT"
    assert config["type_config"]["format"] == "%.3f"
    # Standings (on its Eastern table) writes it with three decimals too.
    east = team_data.standings(MODERN)
    first = east[east.conf == "East"].iloc[0]
    _open(at, "Standings")
    assert f"<td>{first['pct']:.3f}</td>" in _text(at)


def test_the_net_rating_bar_is_centred_on_zero():
    def bar(ratings: list[float]) -> tuple[float, float]:
        config = league._column_config(pd.DataFrame({"net_rating": ratings}))["net_rating"]
        return config["type_config"]["min_value"], config["type_config"]["max_value"]

    # As far each way as the largest rating either side of zero.
    assert bar([-12.5, 1.0, 8.0]) == (-12.5, 12.5)
    assert bar([-3.0, 0.5, 9.0]) == (-9.0, 9.0)
    # Nothing to scale to: a range that still draws.
    assert bar([]) == (-1.0, 1.0)
    assert bar([0.0, 0.0]) == (-1.0, 1.0)


def test_the_four_factors_column_set(con):
    at = _columns(_page(MODERN, **{TEAMS_TAB_KEY: "Team stats"}), "Four Factors")
    shown = _table(at).value
    assert list(shown.columns) == ["team_name", *FOUR_FACTORS]
    assert shown[FOUR_FACTORS].notna().all().all()


def test_a_season_without_ratings_offers_only_basic(con):
    at = _page(EARLY, **{TEAMS_TAB_KEY: "Team stats"})
    assert at.button_group(key=league.COLUMNS_KEY).options == ["Basic"]
    shown = _table(at).value
    assert len(shown) == len(team_data.standings(EARLY))
    # Sorted by point margin when there is no net rating to sort by.
    assert shown["net"].is_monotonic_decreasing
    assert "Ratings are not available before 1985-86." in _captions(at)


def test_without_the_team_mart_team_stats_shows_basic_with_a_note(con, monkeypatch):
    monkeypatch.setattr(advanced, "marts_available", lambda: False)
    at = _page(MODERN, **{TEAMS_TAB_KEY: "Team stats"})
    assert at.button_group(key=league.COLUMNS_KEY).options == ["Basic"]
    assert len(_table(at).value) == len(team_data.standings(MODERN))
    assert "not in this copy of the warehouse yet" in _captions(at)


def test_selecting_a_row_opens_that_team(monkeypatch):
    # Row clicks can't be made through AppTest; this is the dataframe's
    # on_select callback, fed the selection Streamlit would hand it.
    rows = pd.Series(["Boston Celtics", "Utah Jazz"])
    key = table_key(league.TABLE_KEY, "Advanced")
    state = {key: {"selection": {"rows": [1]}}, league.TABLE_ROWS_KEY: rows}
    monkeypatch.setattr(st, "session_state", state)
    league._on_select(key)
    assert state[TEAM_PICK_KEY] == "Utah Jazz"
    assert state[f"{TEAMS_TAB_KEY}__next"] == "Team"

    # A click on a cell (anywhere in the row, not just its checkbox) opens
    # that row's team too.
    state[key] = {"selection": {"rows": [], "cells": [(0, "w")]}}
    league._on_select(key)
    assert state[TEAM_PICK_KEY] == "Boston Celtics"

    # A cleared selection (the row clicked again) opens nobody.
    del state[f"{TEAMS_TAB_KEY}__next"]
    state[key] = {"selection": {"rows": [], "cells": []}}
    league._on_select(key)
    assert f"{TEAMS_TAB_KEY}__next" not in state


def test_the_rows_a_click_is_read_against_match_the_table(con):
    at = _page(MODERN, **{TEAMS_TAB_KEY: "Team stats"})
    shown = _table(at).value
    assert list(at.session_state[league.TABLE_ROWS_KEY]) == list(shown["team_name"])


def test_the_team_tab_opens_on_the_team_a_row_click_chose(con):
    team = _team_names(con, MODERN)[1]
    at = _page(MODERN, **{TEAMS_TAB_KEY: "Team stats"})
    # What _on_select leaves behind, then the rerun Streamlit makes.
    at.session_state[TEAM_PICK_KEY] = team
    at = _open(at, "Team")
    assert at.selectbox(key=TEAM_PICK_KEY).value == team
    assert team in _text(at)


def test_the_team_picker_honours_a_team_set_beforehand(con):
    team = _team_names(con, MODERN)[1]
    at = _page(MODERN, **{TEAM_PICK_KEY: team})
    assert at.selectbox(key=TEAM_PICK_KEY).value == team
    assert team in _text(at)


def test_choices_survive_a_visit_to_another_tab(con):
    team = _team_names(con, MODERN)[1]
    at = _page(MODERN)
    at.selectbox(key=TEAM_PICK_KEY).select(team).run()
    _columns(_open(at, "Team stats"), "Four Factors")
    _open(at, "Standings")
    _open(at, "Team")
    assert at.selectbox(key=TEAM_PICK_KEY).value == team
    # The browser forgot the picker when it left the page, so its value must
    # be sent with it, not just kept on the server.
    assert at.selectbox(key=TEAM_PICK_KEY).proto.set_value
    _open(at, "Team stats")
    assert at.button_group(key=league.COLUMNS_KEY).value == "Four Factors"


def test_a_team_missing_from_the_season_falls_back_to_the_first(con):
    # A team picked in one season that did not exist in another (an
    # expansion team, a relocated franchise's new name).
    modern = set(team_data.standings(MODERN)["team_name"])
    early = team_data.standings(EARLY)
    team = sorted(modern - set(early["team_name"]))[0]
    at = _page(MODERN, **{TEAM_PICK_KEY: team})
    at.selectbox(key="season").select(EARLY).run()
    assert not at.exception, at.exception
    assert at.selectbox(key=TEAM_PICK_KEY).value == early["team_name"].iloc[0]


def test_the_standings_tab_shows_the_table(con):
    at = _open(_page(MODERN), "Standings")
    assert STANDINGS_NOTE in _captions(at)
    standings = team_data.standings(MODERN)
    assert standings[standings.conf == "East"]["team_name"].iloc[0] in _text(at)
    assert all(s.key != TEAM_PICK_KEY for s in at.selectbox)
    assert not [d for d in at.dataframe if d.key in TABLE_KEYS]
