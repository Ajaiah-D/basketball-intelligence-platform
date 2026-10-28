"""The Players page's Scatter tab (dashboard/views/players/scatter.py),
rendered with AppTest against the real warehouse.

The tab has its own season box, which starts at the sidebar's season but
never writes back to it, so the Stats tab's season is not disturbed.
"""

import json

import pytest
from streamlit.testing.v1 import AppTest

from dashboard.lib import glossary
from dashboard.lib import stats as stats_lib
from dashboard.lib import theme as T
from dashboard.lib.data import diagnosis, players, seasons
from dashboard.views.players import scatter

SCRIPT = """
import streamlit as st
from dashboard.lib.data import seasons
from dashboard.views import players
with st.sidebar:
    st.selectbox("Season", seasons.seasons(), key="season")
if st.session_state.get("away"):
    st.write("another page")
else:
    players.render()
"""


def _established_season(con) -> str:
    """The newest season in which someone has played 25+ games."""
    row = con.execute(
        "select max(season) from main_marts.mart_player_season where games_played >= 25"
    ).fetchone()
    if row is None or row[0] is None:
        pytest.skip("no season with a 25-game player in this warehouse")
    return str(row[0])


def _app(season: str | None = None) -> AppTest:
    at = AppTest.from_string(SCRIPT, default_timeout=60)
    if season:
        at.session_state["season"] = season
    at.run()
    assert not at.exception, at.exception
    return at


def _chart(at: AppTest) -> dict:
    """The scatter: the figure whose dashed shapes are the average lines."""
    found = [
        f
        for f in (json.loads(c.proto.spec) for c in at.get("plotly_chart"))
        if f["layout"].get("shapes") and f["data"][0].get("mode") == "markers+text"
    ]
    assert len(found) == 1
    return found[0]


def _dots(fig: dict) -> int:
    return sum(len(t["x"]) for t in fig["data"])


def _caption(at: AppTest) -> str:
    return " ".join(c.value for c in at.tabs[1].caption)


def test_it_opens_on_points_against_true_shooting_for_the_sidebar_season(con):
    season = _established_season(con)
    at = _app(season)
    assert at.selectbox(key=scatter.SEASON_KEY).value == season
    assert at.selectbox(key=scatter.X_KEY).value == "points_per_game"
    assert at.selectbox(key=scatter.Y_KEY).value == "true_shooting_pct"
    assert at.selectbox(key=scatter.TEAM_KEY).value == scatter.ALL_TEAMS
    expected = stats_lib.qualification_threshold(players.player_season_stats(season))
    assert at.slider(key=scatter.MIN_GP_KEY).value == expected
    fig = _chart(at)
    assert fig["layout"]["xaxis"]["title"]["text"] == "PTS"
    assert fig["layout"]["yaxis"]["title"]["text"] == "TS%"
    n = len(diagnosis.league_player_rows(season, expected))
    assert _dots(fig) == n
    assert _caption(at).startswith(f"{n} players with {expected}+ games")


def test_every_metric_has_a_glossary_hover_and_a_column_the_data_layer_returns(con):
    rows = diagnosis.league_player_rows(seasons.latest_season(), 1)
    for key, metric in scatter.METRICS.items():
        assert key in rows.columns, key
        assert metric.term in glossary.TERMS, metric.term
    # The two defaults are metrics, and the pickers open on them.
    assert {scatter.DEFAULT_X, scatter.DEFAULT_Y} <= set(scatter.METRICS)
    assert next(iter(scatter.METRICS)) == scatter.DEFAULT_X


def test_changing_an_axis_changes_the_chart(con):
    at = _app(_established_season(con))
    before = _chart(at)
    at.selectbox(key=scatter.X_KEY).select("usage_pct").run()
    assert not at.exception, at.exception
    after = _chart(at)
    assert after["layout"]["xaxis"]["title"]["text"] == "USG%"
    assert after["data"][0]["x"] != before["data"][0]["x"]
    assert after["data"][0]["y"] == before["data"][0]["y"]
    # The pickers hold their choice across another change.
    at.selectbox(key=scatter.Y_KEY).select("assist_pct").run()
    assert at.selectbox(key=scatter.X_KEY).value == "usage_pct"


def test_the_hover_has_the_player_team_both_values_and_games(con):
    at = _app(_established_season(con))
    hover = _chart(at)["data"][0]["hovertext"][0].split("<br>")
    assert hover[0].startswith("<b>") and "(" in hover[0]
    assert hover[1].startswith("PTS ") and hover[2].startswith("TS% ") and hover[2].endswith("%")
    assert hover[3].endswith(" GP")
    assert not any("#" in line for line in hover)


def test_turnover_rate_runs_high_to_low(con):
    at = _app(_established_season(con))
    at.selectbox(key=scatter.Y_KEY).select("turnover_pct").run()
    assert not at.exception, at.exception
    fig = _chart(at)
    assert fig["layout"]["yaxis"]["autorange"] == "reversed"
    assert "reversed" in fig["layout"]["yaxis"]["title"]["text"]
    assert fig["layout"]["xaxis"].get("autorange") != "reversed"


def test_the_team_filter_highlights_and_labels_all_of_its_players(con):
    season = _established_season(con)
    at = _app(season)
    options = at.selectbox(key=scatter.TEAM_KEY).options
    assert options[0] == scatter.ALL_TEAMS and len(options) > 2
    team = options[1]
    at.selectbox(key=scatter.TEAM_KEY).select(team).run()
    assert not at.exception, at.exception

    fig = _chart(at)
    assert len(fig["data"]) == 2
    mark = fig["data"][1]
    rows = diagnosis.league_player_rows(season, at.slider(key=scatter.MIN_GP_KEY).value)
    on_team = _on_team(rows, team)
    assert len(mark["x"]) == len(on_team) >= 1
    assert sorted(mark["text"]) == sorted(on_team["player"])
    assert f"{team} highlighted" in _caption(at)
    # Every highlighted dot wears the filtered team's colour, whichever team
    # a traded player finished with.
    assert set(mark["marker"]["color"]) == {T.team_color(team)}
    # The highlighted team does not change who is plotted or the average.
    assert _dots(fig) == len(rows)


def test_a_team_with_nobody_at_the_new_minimum_is_dropped_from_the_filter(con):
    season = _established_season(con)
    at = _app(season)
    # A team on the list now that nobody has played the full 82 games for.
    team = next(
        t
        for t in at.selectbox(key=scatter.TEAM_KEY).options[1:]
        if _on_team(diagnosis.league_player_rows(season, 82), t).empty
    )
    at.selectbox(key=scatter.TEAM_KEY).select(team).run()
    assert at.selectbox(key=scatter.TEAM_KEY).value == team
    at.slider(key=scatter.MIN_GP_KEY).set_value(82).run()
    assert not at.exception, at.exception
    assert team not in at.selectbox(key=scatter.TEAM_KEY).options
    assert at.selectbox(key=scatter.TEAM_KEY).value == scatter.ALL_TEAMS


def test_min_games_returns_to_the_qualification_default_when_its_widget_state_is_dropped(con):
    season = _established_season(con)
    at = _app(season)
    expected = stats_lib.qualification_threshold(players.player_season_stats(season))
    at.slider(key=scatter.MIN_GP_KEY).set_value(expected + 3).run()
    assert at.slider(key=scatter.MIN_GP_KEY).value == expected + 3
    # Streamlit drops a widget's state when the tab or page isn't rendered on a
    # run; the slider is then rebuilt with nothing, which used to read as 1.
    at.session_state["away"] = True
    at.run()
    assert not at.exception, at.exception
    assert scatter.MIN_GP_KEY not in at.session_state
    at.session_state["away"] = False
    at.run()
    assert not at.exception, at.exception
    assert at.slider(key=scatter.MIN_GP_KEY).value == expected


def _on_team(rows, team: str):
    return rows[rows["team_label"].str.contains(team, regex=False)]


def _plottable(season: str, x: str, y: str):
    """The rows the scatter can draw at its default minimum: non-null on both."""
    minimum = stats_lib.qualification_threshold(players.player_season_stats(season))
    rows = diagnosis.league_player_rows(season, minimum)
    return rows, rows.dropna(subset=[x, y])


def test_the_caption_counts_the_dots_drawn_not_every_qualified_player(con):
    # 1979-80 has no true shooting for part of the league: those players are
    # qualified but cannot be plotted.
    season = "1979-80"
    rows, drawn = _plottable(season, "points_per_game", "true_shooting_pct")
    assert 0 < len(drawn) < len(rows)
    at = _app(season)
    assert at.selectbox(key=scatter.SEASON_KEY).value == season
    assert _dots(_chart(at)) == len(drawn)
    assert _caption(at).startswith(f"{len(drawn)} players with ")


@pytest.mark.parametrize(
    ("season", "x"), [("1990-91", "player_impact_estimate"), ("1979-80", "usage_pct")]
)
def test_a_stat_nobody_has_that_season_is_one_info_line_and_no_chart(con, season, x):
    # PIE is null before 1996-97 and usage before 1985-86.
    _, drawn = _plottable(season, x, "true_shooting_pct")
    assert drawn.empty
    at = _app(season)
    at.selectbox(key=scatter.X_KEY).select(x).run()
    assert not at.exception, at.exception
    assert [i.value for i in at.tabs[1].info] == [
        f"No player has both {scatter.METRICS[x].label} and TS% in {season}."
    ]
    assert not at.tabs[1].get("plotly_chart")
    assert not at.tabs[1].caption


def test_the_same_stat_on_both_axes_renders(con):
    at = _app(_established_season(con))
    at.selectbox(key=scatter.Y_KEY).select(scatter.DEFAULT_X).run()
    assert not at.exception, at.exception


def test_its_own_season_leaves_the_stats_tabs_season_alone(con):
    every = seasons.seasons()
    if len(every) < 2:
        pytest.skip("needs a warehouse with two seasons")
    newest, older = every[0], every[1]
    at = _app(newest)
    at.selectbox(key=scatter.SEASON_KEY).select(older).run()
    assert not at.exception, at.exception
    assert at.session_state["season"] == newest
    assert at.selectbox(key="players_season").value == newest
    assert at.selectbox(key=scatter.SEASON_KEY).value == older
    # The minimum games follows the season it was set for.
    expected = stats_lib.qualification_threshold(players.player_season_stats(older))
    assert at.slider(key=scatter.MIN_GP_KEY).value == expected


def test_the_sidebar_season_moves_the_scatter_season(con):
    every = seasons.seasons()
    if len(every) < 2:
        pytest.skip("needs a warehouse with two seasons")
    at = _app(every[0])
    at.selectbox(key="season").select(every[1]).run()
    assert not at.exception, at.exception
    assert at.selectbox(key=scatter.SEASON_KEY).value == every[1]
