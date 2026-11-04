"""Teams - one team in depth, every team side by side, and the standings,
each in its own tab.

  team.py       the Team tab: ratings, splits, league ranks on every key
                stat, the player breakdown, charts and the roster
  profile.py    the league-ranks section (or the Four Factors on an older
                warehouse)
  breakdown.py  the player breakdown: the rotation on one area at a time
  league.py     the Team stats tab: every team's ratings and Four Factors;
                a row click opens that team on the Team tab
  standings.py  the Standings tab
  common.py     the tab and team-picker keys, the heading style and the
                grid row height the tabs share

This module is the page: a title and the three tabs. Only the active tab is
drawn (lib.tabs.keyed_tabs), so a Team stats row click switches tabs by
setting state, and the hidden tabs cost nothing.
"""

import streamlit as st

from dashboard.lib import theme as T
from dashboard.lib.data import seasons
from dashboard.lib.data import teams as team_data
from dashboard.lib.state import SEASON_KEY
from dashboard.lib.tabs import keyed_tabs
from dashboard.lib.widget_state import hold_keys
from dashboard.views.teams import breakdown, league, scatter
from dashboard.views.teams.common import TEAM_PICK_KEY, TEAMS_TAB_KEY
from dashboard.views.teams.standings import CONF_KEY, render_standings
from dashboard.views.teams.team import render_team

TABS = ["Team", "Team stats", "Standings"]

# The choices each tab keeps while another tab is open (lib.widget_state.
# hold_keys): the team, the Team tab's area and scatter pickers, the column
# set and the conference.
KEPT_KEYS = [
    TEAM_PICK_KEY,
    breakdown.AREA_KEY,
    scatter.X_KEY,
    scatter.Y_KEY,
    league.COLUMNS_KEY,
    CONF_KEY,
]


def render() -> None:
    season = st.session_state.get(SEASON_KEY) or seasons.latest_season()
    hold_keys(KEPT_KEYS)
    st.markdown(f"## Teams &nbsp;{T.chip(season)}", unsafe_allow_html=True)
    standings = team_data.standings(season)

    active, tabs = keyed_tabs(TABS, TEAMS_TAB_KEY)
    with tabs[active]:
        if active == "Team":
            render_team(season, standings)
        elif active == "Team stats":
            league.render_team_stats(season, standings)
        else:
            render_standings(standings)
