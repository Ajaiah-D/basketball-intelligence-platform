"""The Team tab's two-stat scatter: every team that season on any two
profile stats, the open team highlighted. It shows where teams sit and
leaves the reading to the viewer, so the dashed league-average lines are
the only reference and no quadrant is named.

A warehouse published before mart_team_profile has only the ratings, so it
gets the one fixed pair, offense against defense, without the pickers.
"""

import pandas as pd
import streamlit as st

from dashboard.lib import diagnosis, glossary, viz, viz_diagnosis
from dashboard.lib.data import diagnosis as diagnosis_data
from dashboard.views.teams.common import section

X_KEY = "teams_scatter_x"
Y_KEY = "teams_scatter_y"
DEFAULT_X = "offensive_rating"
DEFAULT_Y = "defensive_rating"
CHART_HEIGHT = 360
# A stat needs this many teams with a value to be worth plotting: early
# seasons have a handful of columns and the rest null.
MIN_TEAMS = 5


def _stat_term(key: str) -> str | None:
    return glossary.TERMS.get(diagnosis.PROFILE_BY_KEY[key].term)


def _pick(label: str, key: str, options: list[str], default: str) -> str:
    """A compact stat picker whose hover explains the stat now selected."""
    # A stat the new season has no values for leaves a stale choice behind.
    if st.session_state.get(key) not in options:
        st.session_state.pop(key, None)
    st.session_state.setdefault(key, default)
    return st.selectbox(
        label,
        options,
        key=key,
        format_func=lambda k: diagnosis.PROFILE_BY_KEY[k].label,
        help=_stat_term(st.session_state[key]),
    )


def render_scatter(
    season: str, team: str, standings: pd.DataFrame, adv: pd.DataFrame, has_ratings: bool
) -> None:
    """The section for one team-season. `adv` (mart_team_season) feeds only
    the fallback; `standings` supplies team names, which the profile mart
    does not carry."""
    if not diagnosis_data.profile_available():
        if has_ratings:
            _ratings_scatter(adv, team)
        return

    league = diagnosis_data.team_profile(season)
    options = [
        s.key
        for s in diagnosis.PROFILE_STATS
        if s.key in league.columns and league[s.key].notna().sum() >= MIN_TEAMS
    ]
    # Two stats to compare, and the default pair when the season has it.
    if len(options) < 2:
        return
    names = standings.drop_duplicates("team_id").set_index("team_id")["team_name"]
    league["team_name"] = league["team_id"].map(names).fillna(league["team_abbreviation"])

    section("Compare two stats", glossary.TERMS["Compare two stats"])
    left, right = st.columns(2)
    with left:
        x = _pick("Horizontal", X_KEY, options, DEFAULT_X if DEFAULT_X in options else options[0])
    with right:
        y = _pick("Vertical", Y_KEY, options, DEFAULT_Y if DEFAULT_Y in options else options[1])

    # Reverse only the axes where the league's #1 is the low end; the style
    # stats (pace, 3-pt rate) rank from the most, so they never are.
    invert = tuple(
        k
        for k in (x, y)
        if diagnosis.PROFILE_BY_KEY[k].judged and viz_diagnosis.lower_is_better(league, k)
    )
    fig = viz_diagnosis.stat_scatter(
        league,
        x,
        y,
        label_col="team_abbreviation",
        color_col="team_abbreviation",
        highlight=team,
        x_label=diagnosis.PROFILE_BY_KEY[x].label,
        y_label=diagnosis.PROFILE_BY_KEY[y].label,
        label_top=len(league),
        invert=invert,
        name_col="team_name",
        fmt=viz_diagnosis.format_value,
    )
    fig.update_layout(height=CHART_HEIGHT)
    st.plotly_chart(fig, config=viz.PLOTLY_CONFIG, width="stretch")


def _ratings_scatter(adv: pd.DataFrame, team: str) -> None:
    """The fixed offense-against-defense pair, from the ratings alone."""
    # The two ratings' own hovers: "Compare two stats" talks about a picker
    # this version does not have.
    section(
        "Offense vs defense",
        f"Offensive rating: {glossary.TERMS['Offensive rating']} "
        f"Defensive rating: {glossary.TERMS['Defensive rating']}",
    )
    fig = viz_diagnosis.stat_scatter(
        adv,
        "offensive_rating",
        "defensive_rating",
        label_col="team_abbreviation",
        color_col="team_abbreviation",
        highlight=team,
        x_label="Offensive rating",
        y_label="Defensive rating",
        label_top=len(adv),
        # Hard-coded: the ratings frame has no rank columns to read it from.
        invert=("defensive_rating",),
        name_col="team_name",
    )
    fig.update_layout(height=CHART_HEIGHT)
    st.plotly_chart(fig, config=viz.PLOTLY_CONFIG, width="stretch")
