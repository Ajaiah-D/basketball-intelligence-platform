"""Teams - one team in depth, with full standings in their own tab so the
table doesn't crowd out the team view.

  team.py       the Team tab: ratings, splits, league ranks on every key
                stat, the player breakdown, charts and the roster
  profile.py    the league-ranks section (or the Four Factors on an older
                warehouse)
  breakdown.py  the player breakdown: the rotation on one area at a time
  standings.py  the Standings tab
  common.py     the heading style and grid row height both tabs share

This module is the page: a title and the two tabs.
"""

import streamlit as st

from dashboard.lib import theme as T
from dashboard.lib.data import seasons
from dashboard.lib.data import teams as team_data
from dashboard.lib.state import SEASON_KEY
from dashboard.views.teams.standings import render_standings
from dashboard.views.teams.team import render_team


def render() -> None:
    season = st.session_state.get(SEASON_KEY) or seasons.latest_season()
    st.markdown(f"## Teams &nbsp;{T.chip(season)}", unsafe_allow_html=True)
    standings = team_data.standings(season)

    tab_team, tab_standings = st.tabs(["Team", "Standings"])
    with tab_standings:
        render_standings(standings)
    with tab_team:
        render_team(season, standings)
