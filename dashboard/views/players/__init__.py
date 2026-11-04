"""Players - a search for any player above four tabs: the league table, one
player in depth, a head-to-head compare and a scatter of the league.

  search.py    the player search, and open_player (how anything opens the Player tab)
  table.py     the All players tab: the filterable table; a row click opens that player
  player.py    the Player tab: one player, a titled section per question
  game_log.py  the Player tab's game log and game-by-game trend
  compare.py   the Compare tab
  scatter.py   the Scatter tab

This module is the page: a title, the search and the tabs. Only the active
tab is drawn (lib.tabs.keyed_tabs), so the search or a row click switches
tabs by setting state, and the hidden tabs cost nothing.
"""

import streamlit as st

from dashboard.lib import theme as T
from dashboard.lib.data import players, seasons
from dashboard.lib.state import PLAYERS_PICK_KEY, SEASON_KEY
from dashboard.lib.tabs import keyed_tabs
from dashboard.views.players import player, table
from dashboard.views.players.compare import render_compare
from dashboard.views.players.scatter import render_scatter
from dashboard.views.players.search import PLAYERS_TAB_KEY, open_player, render_search

TABS = ["All players", "Player", "Compare", "Scatter"]
# The All players table as last drawn: only one tab runs per pass, and the
# Player tab opens on its top row when nobody has been chosen.
_DEFAULT_ROWS_KEY = "players_default_rows"


def _apply_preset(season: str) -> None:
    """Open the player another page asked for (state.PLAYERS_PICK_KEY, set
    with the season by Teams' "Open on Players"). It is read once: the
    player opens in the Player tab, and the min-games slider drops to his
    games when he has fewer than it asks for (a team's rotation starts at 10
    games), so he is in the All players table too. A name nobody has this
    season is ignored. Runs after reset_min_games, so a new season's reset
    doesn't undo the lowered slider, and before the tabs are drawn, so the
    Player tab opens on this run without a rerun."""
    preset = st.session_state.pop(PLAYERS_PICK_KEY, None)
    if not preset:
        return
    season_stats = players.player_season_stats(season)
    match = season_stats[season_stats["player"] == preset]
    if match.empty:
        return
    open_player(int(match["player_id"].iloc[0]), season)
    table.lower_min_games(int(match["gp"].min()))


def render() -> None:
    season = st.session_state.get(SEASON_KEY) or seasons.latest_season()
    table.keep_filters(player.KEPT_KEYS)
    table.reset_min_games(season)
    _apply_preset(season)

    # The All players tab fills the title in once its scope toggle (one
    # season or the career) is known; the other tabs show the season.
    head = st.container()
    render_search(season)
    active, tabs = keyed_tabs(TABS, PLAYERS_TAB_KEY)
    if active != "All players":
        head.markdown(f"## Players &nbsp;{T.chip(season)}", unsafe_allow_html=True)

    with tabs[active]:
        if active == "All players":
            st.session_state[_DEFAULT_ROWS_KEY] = table.render_table(head)
        elif active == "Player":
            player.render_player(st.session_state.get(_DEFAULT_ROWS_KEY), season)
        elif active == "Compare":
            render_compare()
        else:
            render_scatter()
