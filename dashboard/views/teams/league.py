"""The Teams page's Team stats tab: every team that season in one table,
highest net rating first, where a click on a row opens that team on the
Team tab.

The Columns control picks one of three column sets. Basic reads the
standings (mart_team_standings), which every published warehouse has.
Advanced and Four Factors add the ratings and rates from mart_team_season
(data.advanced.team_advanced), joined on team_id from the standings side so
the table still lists every team when the mart lacks one. They are offered
only when the mart is in the warehouse and the season has ratings: before
1985-86 the box score is missing the columns they are computed from.
"""

from __future__ import annotations

from functools import partial

import pandas as pd
import streamlit as st

from dashboard.lib import glossary
from dashboard.lib import theme as T
from dashboard.lib.data import advanced
from dashboard.lib.tabs import open_tab
from dashboard.lib.widget_state import choice, selected_position
from dashboard.views.teams.common import ROW_HEIGHT, TEAM_PICK_KEY, TEAMS_TAB_KEY

# Session-state keys.
COLUMNS_KEY = "teams_columns"
# The table's key is this plus the column set (table_key).
TABLE_KEY = "teams_table"
# The team name of each row of the table as drawn, in order: a row click
# arrives as a position, and this turns it into a team.
TABLE_ROWS_KEY = "teams_table_rows"

# The column sets, by the frame's column names.
COLUMN_SETS = {
    "Basic": ["team_name", "w", "l", "win_pct", "ppg", "opp_ppg", "net"],
    "Advanced": [
        "team_name",
        "w",
        "l",
        "offensive_rating",
        "defensive_rating",
        "net_rating",
        "pace",
        "true_shooting_pct",
        "effective_fg_pct",
        "assist_pct",
    ],
    "Four Factors": [
        "team_name",
        "effective_fg_pct",
        "turnover_pct",
        "offensive_rebound_pct",
        "free_throw_rate",
        "opp_effective_fg_pct",
        "opp_turnover_pct",
        "defensive_rebound_pct",
        "opp_free_throw_rate",
    ],
}
# What the table takes from mart_team_season: the Advanced and Four Factors
# columns. The name and record come from the standings, so they are not
# taken twice.
MART_COLS = [
    *dict.fromkeys(
        c
        for s in ("Advanced", "Four Factors")
        for c in COLUMN_SETS[s]
        if c not in COLUMN_SETS["Basic"]
    ),
    "ratings_source",
]
# Column -> (header, glossary entry) for the mart's rates. The headers are
# the short forms a box score uses; several share a label with a player
# stat, so each names the team entry that explains it.
RATE_TERMS = {
    "offensive_rating": ("ORtg", "Offensive rating"),
    "defensive_rating": ("DRtg", "Defensive rating"),
    "pace": ("Pace", "Pace"),
    "true_shooting_pct": ("TS%", "TS%"),
    "effective_fg_pct": ("eFG%", "eFG%"),
    "assist_pct": ("AST%", "Assist rate"),
    "turnover_pct": ("TOV%", "Turnover rate"),
    "offensive_rebound_pct": ("OREB%", "Off. rebound %"),
    "free_throw_rate": ("FT rate", "FT rate"),
    "opp_effective_fg_pct": ("Opp eFG%", "Opp eFG%"),
    "opp_turnover_pct": ("Opp TOV%", "Opp turnover rate"),
    "defensive_rebound_pct": ("DREB%", "Def. rebound %"),
    "opp_free_throw_rate": ("Opp FT rate", "Opp FT rate"),
}

NO_MART = "Ratings and the Four Factors are not in this copy of the warehouse yet."


def _frame(season: str, standings: pd.DataFrame) -> pd.DataFrame:
    """The standings with the mart's columns joined on, highest net rating
    first. A season without ratings (or a warehouse without the mart) sorts
    by point margin instead, and the team abbreviation settles a tie so a
    rerun can't reshuffle one."""
    view = standings.assign(win_pct=standings["pct"] * 100)
    if advanced.marts_available():
        mart = advanced.team_advanced(season)
        # An older warehouse may lack a column; it is left out, not an error.
        keep = [c for c in MART_COLS if c in mart.columns]
        view = view.merge(mart[["team_id", *keep]], on="team_id", how="left")
    by = [c for c in ("net_rating", "net") if c in view.columns]
    view = view.sort_values([*by, "team"], ascending=[*[False] * len(by), True], na_position="last")
    # Positions, not labels: a row click comes back as a position.
    return view.reset_index(drop=True)


def _column_config(view: pd.DataFrame) -> dict:
    """Every column's header, hover text and format, with net rating as the
    one bar. The bar runs from the season's lowest net rating to its
    highest rather than from zero, which would leave every negative rating
    an empty bar; zero is always inside the range, and the signed value
    beside the bar says which side of it a team is on."""
    net = view["net_rating"].dropna() if "net_rating" in view else pd.Series(dtype=float)
    low = float(min(0.0, net.min())) if len(net) else -1.0
    high = float(max(0.0, net.max())) if len(net) else 1.0
    if high <= low:
        high = low + 1.0
    return {
        "team_name": st.column_config.TextColumn("Team", width="medium"),
        "w": st.column_config.NumberColumn("W"),
        "l": st.column_config.NumberColumn("L"),
        "win_pct": st.column_config.NumberColumn(
            **glossary.described("Win%", "PCT"), format="%.1f"
        ),
        "ppg": st.column_config.NumberColumn("PTS", format="%.1f"),
        "opp_ppg": st.column_config.NumberColumn(
            **glossary.described("OPP PTS", "OPP"), format="%.1f"
        ),
        "net": st.column_config.NumberColumn(
            **glossary.described("Net/game", "Net / game"), format="%+.1f"
        ),
        **{
            col: st.column_config.NumberColumn(**glossary.marked(label, term), format="%.1f")
            for col, (label, term) in RATE_TERMS.items()
        },
        "net_rating": st.column_config.ProgressColumn(
            **glossary.marked("NET", "Net rating"),
            format="%+.1f",
            min_value=low,
            max_value=high,
            color=T.ACCENT,
            width="medium",
        ),
    }


def table_key(columns: str) -> str:
    """The table's key for one column set ("teams_table_four_factors").

    One key per set, so switching sets draws a new grid rather than
    reshaping the old one. A reshaped grid ignores the first click on a
    cell after the switch (only its row checkbox still worked), so the
    reader's first click on a team did nothing."""
    return f"{TABLE_KEY}_{columns.lower().replace(' ', '_')}"


def _on_select(key: str) -> None:
    """The table's on_select (`key` is the table's): open the clicked row's
    team on the Team tab (lib.widget_state.selected_position). A click that
    clears the selection opens nothing. The rerun after a callback draws
    the Team tab with the picker already on the team."""
    position = selected_position(key)
    if position is None:
        return
    st.session_state[TEAM_PICK_KEY] = str(st.session_state[TABLE_ROWS_KEY].iloc[position])
    open_tab(TEAMS_TAB_KEY, "Team")


def _captions(view: pd.DataFrame, has_mart: bool) -> None:
    """How to use the table, and where the ratings come from: the NBA's own
    figures, estimates from the box score, or none that season."""
    sources = (
        view["ratings_source"].dropna() if "ratings_source" in view else pd.Series(dtype=object)
    )
    line = "Click a row to open that team."
    if len(sources):
        line += f" Ratings are {sources.iloc[0]}."
    st.caption(line)
    if not has_mart:
        st.caption(NO_MART)


def render_team_stats(season: str, standings: pd.DataFrame) -> None:
    """The Team stats tab: a Columns control over one table of every team."""
    has_mart = advanced.marts_available()
    view = _frame(season, standings)
    has_ratings = "net_rating" in view and bool(view["net_rating"].notna().any())
    sets = list(COLUMN_SETS) if has_ratings else ["Basic"]
    columns = choice(COLUMNS_KEY, sets)
    # required: a click on the chosen set keeps it, rather than clearing the
    # control and sending it back to Basic.
    st.segmented_control(
        "Columns",
        sets,
        required=True,
        label_visibility="collapsed",
        key=COLUMNS_KEY,
        help="Which stats the table shows",
    )
    table_cols = [c for c in COLUMN_SETS[columns] if c in view.columns]

    st.session_state[TABLE_ROWS_KEY] = view["team_name"]
    key = table_key(columns)
    st.dataframe(
        view[table_cols],
        hide_index=True,
        # Every team without a scrollbar: a league is at most 30 rows.
        height=(len(view) + 1) * ROW_HEIGHT + 3,
        row_height=ROW_HEIGHT,
        column_config=_column_config(view),
        # st.dataframe takes no callback args, hence the partial.
        on_select=partial(_on_select, key),
        # Row selection alone only reacts to the checkbox at the left edge;
        # cell selection too makes a click anywhere on the row open the team.
        selection_mode=["single-row", "single-cell"],
        key=key,
    )
    _captions(view, has_mart)
