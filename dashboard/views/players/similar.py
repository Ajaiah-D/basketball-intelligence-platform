"""The Players page's Similar players tab: the players whose season looks
most like the chosen player's, ranked by lib.similarity.

The player is the Player tab's (player.picked_player), at his season there,
so the two tabs always agree on who and when. A slider sets how many to
list, and a click on a row opens that player in the Player tab.
"""

from __future__ import annotations

from functools import partial

import pandas as pd
import streamlit as st

from core.constants import COMPLETE_BOX_SCORE_FIRST_SEASON
from dashboard.lib import glossary, media, similarity
from dashboard.lib import theme as T
from dashboard.lib.advanced_metrics import PLAYER_COLUMN_CONFIG, minutes_floor
from dashboard.lib.data import advanced
from dashboard.lib.widget_state import selected_position
from dashboard.views.players.player import picked_player
from dashboard.views.players.search import open_player

# How many players the list holds: the slider's range and starting value.
N_MIN, N_MAX, N_DEFAULT = 5, 25, 10
SIMILAR_N_KEY = "players_similar_n"
# The table's key is this plus the player and season, so a selection left
# on one player's list doesn't carry over to the next.
SIMILAR_TABLE_KEY = "players_similar_table"
# (player_id, season) for each row of the table as drawn: a click arrives
# as a position, and this turns it into a player.
SIMILAR_ROWS_KEY = "players_similar_rows"
# The tab's widgets, which the page keeps while another tab is open.
KEPT_KEYS = [SIMILAR_N_KEY]

# The columns the list shows, in order.
COLUMNS = [
    "rank",
    "player_name",
    "team_label",
    "games_played",
    "minutes_per_game",
    "points_per_game",
    "rebounds_per_game",
    "assists_per_game",
    "true_shooting_pct",
    "usage_pct",
    "similarity",
]


def _column_config() -> dict:
    return {
        "rank": st.column_config.NumberColumn("#", width="small"),
        "player_name": st.column_config.TextColumn("Player", width="medium"),
        "team_label": st.column_config.TextColumn(
            "Team",
            width="small",
            help="Two teams (CHI → BOS) means traded mid-season; the line covers both",
        ),
        "games_played": st.column_config.NumberColumn(**glossary.described("GP")),
        "minutes_per_game": st.column_config.NumberColumn(
            **glossary.described("MIN"), format="%.1f"
        ),
        "points_per_game": st.column_config.NumberColumn("PTS", format="%.1f"),
        "rebounds_per_game": st.column_config.NumberColumn("REB", format="%.1f"),
        "assists_per_game": st.column_config.NumberColumn("AST", format="%.1f"),
        "true_shooting_pct": st.column_config.NumberColumn(**glossary.marked("TS%"), format="%.1f"),
        "usage_pct": PLAYER_COLUMN_CONFIG["usage_pct"],
        "similarity": st.column_config.ProgressColumn(
            "Similarity",
            help="Cosine similarity of the two players' capped z-scores: 1 is the same "
            "profile, 0 unrelated",
            format="%.2f",
            min_value=0.0,
            max_value=1.0,
            color=T.ACCENT,
            width="medium",
        ),
    }


def _on_select(key: str) -> None:
    """The table's on_select: open the clicked row's player in the Player
    tab (lib.widget_state.selected_position). A cleared selection opens
    nobody."""
    position = selected_position(key)
    if position is None:
        return
    row = st.session_state[SIMILAR_ROWS_KEY].iloc[position]
    open_player(int(row["player_id"]), str(row["season"]))


def _header(me: pd.Series, season: str) -> None:
    """Whose list this is: avatar, name, team and season."""
    tc = T.team_color(me["team"])
    where = T.chip(f"{me['team_label']} &middot; {season}", tc)
    st.markdown(
        f'<div style="display:flex;align-items:center;gap:12px;margin:.4rem 0 .6rem 0">'
        f"{media.avatar_html(int(me['player_id']), me['player_name'], size=56, ring=tc)}"
        f'<div><span style="font-size:1.25rem;font-weight:800;letter-spacing:-.02em">'
        f"Players most like {me['player_name']}</span><br>"
        f"{where}</div></div>",
        unsafe_allow_html=True,
    )


def method_caption(features: list[str], floor: int, pool_size: int, season: str) -> str:
    """The line under the list that says how it was ranked."""
    labels = ", ".join(similarity.FEATURES[c] for c in features)
    return (
        f"Compared with the {pool_size} players who played {floor}+ minutes in {season}, "
        f"on {len(features)} stats: {labels}. Each stat is turned into a z-score over "
        f"those players (capped at ±{similarity.Z_CAP:g}, so no single stat decides a "
        "match), and players are ranked by the cosine similarity of their z-scores. "
        "Rates and shares rather than totals, so he is matched on how he plays more "
        "than how much. The data has no positions, so they play no part. "
        "Click a row to open that player."
    )


def render_similar(default_rows: pd.DataFrame | None, season: str) -> None:
    """The Similar players tab at the page's `season`. `default_rows` is the
    All players table as last drawn, as for the Player tab."""
    picked = picked_player(default_rows, season)
    if picked is None:
        st.info(f"No player stats for {season} yet.")
        return
    at = picked.season
    if not advanced.marts_available():
        st.caption("Similar players needs advanced stats, which this warehouse doesn't have yet.")
        return
    if at not in advanced.advanced_seasons():
        st.caption(
            f"No similar players for {at}: the comparison uses advanced stats, which "
            f"start in {COMPLETE_BOX_SCORE_FIRST_SEASON}, the first season with complete "
            "box scores."
        )
        return
    pool = advanced.player_advanced(at)
    mine = pool[pool["player_id"] == picked.player_id]
    if mine.empty:
        st.info(f"No {at} line for this player.")
        return
    me = mine.iloc[0]
    _header(me, at)

    floor = minutes_floor(pool)
    if me["minutes"] < floor:
        st.caption(
            f"{me['player_name']} played {int(me['minutes'])} minutes in {at}, under the "
            f"{floor}-minute floor: too few to compare."
        )
        return

    st.session_state.setdefault(SIMILAR_N_KEY, N_DEFAULT)
    slider, _ = st.columns([2, 3])
    n = slider.slider("Players to show", N_MIN, N_MAX, key=SIMILAR_N_KEY)
    result = similarity.rank_similar(pool, picked.player_id, floor, n)
    ranked = result.ranked.assign(similarity=result.ranked["similarity"].clip(lower=0.0))

    st.session_state[SIMILAR_ROWS_KEY] = pd.DataFrame(
        {"player_id": ranked["player_id"], "season": at}
    )
    key = f"{SIMILAR_TABLE_KEY}_{picked.player_id}_{at}"
    st.dataframe(
        ranked[COLUMNS],
        hide_index=True,
        height=(len(ranked) + 1) * 38 + 3,
        row_height=38,
        column_config=_column_config(),
        on_select=partial(_on_select, key),
        # Cell selection too, so a click anywhere on the row opens him.
        selection_mode=["single-row", "single-cell"],
        key=key,
    )
    st.caption(method_caption(result.features, floor, result.pool_size, at))
