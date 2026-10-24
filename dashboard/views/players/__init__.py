"""Players - the stats table and one player in depth, a scatter of the
league and a head-to-head compare, each in its own tab.

  stats.py     the Stats tab: the searchable table and the player detail
  game_log.py  the season detail's game log and game-by-game trend
  scatter.py   the Scatter tab
  compare.py   the Compare tab

This module is the page: a title and the three tabs.
"""

import streamlit as st

from dashboard.views.players.compare import render_compare
from dashboard.views.players.scatter import render_scatter
from dashboard.views.players.stats import render_stats


def render() -> None:
    # The Stats tab fills the title in once its scope toggle (one season or
    # the career) is known. Stats is the first tab, so a player another page
    # sent here (state.PLAYERS_PICK_KEY) opens in front of the reader.
    head = st.container()
    tab_stats, tab_scatter, tab_compare = st.tabs(["Stats", "Scatter", "Compare"])
    with tab_stats:
        render_stats(head)
    with tab_scatter:
        render_scatter()
    with tab_compare:
        render_compare()
