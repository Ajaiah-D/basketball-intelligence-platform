"""The Players page's player search, and the one way into the Player tab.

The search sits above the tabs and lists every player in the warehouse,
retired ones included (data.players.all_players_index). Picking one opens
the Player tab on him at the sidebar's season if he played it, otherwise at
his most recent season.

open_player is how anything on the page (the search, a click on an All
players row, a preset from the Teams page) chooses the player: it sets the
keys the Player tab reads and queues that tab. The tab key lives here, not
in the package __init__, so table.py and this module don't import the page.
"""

from __future__ import annotations

import streamlit as st

from core.text import fold
from dashboard.lib.data import players, seasons
from dashboard.lib.state import SEASON_KEY
from dashboard.lib.tabs import open_tab

PLAYERS_TAB_KEY = "players_tab"
PLAYER_ID_KEY = "players_player_id"
PLAYER_SEASON_KEY = "players_player_season"
# The sidebar season when he was chosen. The Player tab compares it with the
# sidebar's on each run, and moves him to a newly picked season he played.
PLAYER_PICKED_AT_KEY = "players_player_picked_at"
# The Player tab's own Season / Career toggle.
PLAYER_SCOPE_KEY = "players_player_scope"
SEARCH_KEY = "players_search"


def open_player(player_id: int, season: str, career: bool = False) -> None:
    """Show `player_id` at `season` on the Player tab (his career when
    `career`) and switch to that tab. From then on he follows the sidebar
    season to any season he played (player.picked_player). Call it from a widget
    callback, or from the page body before the tabs are drawn; anywhere else
    needs a st.rerun() after it (lib.tabs.open_tab)."""
    st.session_state[PLAYER_ID_KEY] = int(player_id)
    st.session_state[PLAYER_SEASON_KEY] = season
    st.session_state[PLAYER_PICKED_AT_KEY] = (
        st.session_state.get(SEASON_KEY) or seasons.latest_season()
    )
    st.session_state[PLAYER_SCOPE_KEY] = "Career" if career else "Season"
    open_tab(PLAYERS_TAB_KEY, "Player")


def _plain(name: str) -> str:
    """`name` in plain ASCII letters, case kept ("Jokić" -> "Jokic"), by the
    same rules as core.text.fold."""
    return "".join(fold(ch).upper() if ch.isupper() else fold(ch) for ch in name)


def _labels() -> dict[int, str]:
    """player_id -> "Name · TEAM · latest season".

    The select filters on these labels as typed, accents included, so an
    accented name carries its plain spelling too ("Nikola Jokić (Nikola
    Jokic) · DEN · 2026-27"): typing "jokic" finds him, as it does in every
    other search box (core.text). The select also sends back the label, not
    the id, so two players with the same label (one name, one team, one last
    season) get their id added to tell them apart."""
    index = players.all_players_index()
    names = index["player"].fillna("")
    plain = names.map(_plain)
    names = names.where(plain == names, names + " (" + plain + ")")
    labels = names + " · " + index["team"] + " · " + index["latest_season"]
    clash = labels.duplicated(keep=False)
    labels = labels.where(~clash, labels + " · #" + index["player_id"].astype(str))
    return dict(zip(index["player_id"].astype(int), labels, strict=True))


def _on_pick(season: str) -> None:
    """The search's on_change: open the picked player, then empty the box so
    picking the same player again later is still a change."""
    player_id = st.session_state.get(SEARCH_KEY)
    if player_id is None:
        return
    index = players.all_players_index()
    latest = index.loc[index["player_id"] == player_id, "latest_season"].iloc[0]
    played = player_id in set(players.player_season_stats(season)["player_id"])
    open_player(player_id, season if played else latest)
    # Allowed here: a callback runs before the widget is drawn again.
    st.session_state[SEARCH_KEY] = None


def render_search(season: str) -> None:
    """The full-width search. Its key puts the class st-key-players_search
    on it, which lib.theme styles as a taller box with larger text."""
    labels = _labels()
    st.selectbox(
        "Find a player",
        list(labels),
        index=None,
        format_func=labels.__getitem__,
        placeholder="Search any player",
        label_visibility="collapsed",
        # Substring, not the default fuzzy subsequence: with ~4,000 names a
        # fuzzy "jokic" ranks Joe Kopicki ("JOe KopICki") first.
        filter_mode="contains",
        key=SEARCH_KEY,
        on_change=_on_pick,
        args=(season,),
    )
