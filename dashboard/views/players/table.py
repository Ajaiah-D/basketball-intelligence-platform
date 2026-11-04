"""The Players page's All players tab: one filterable table of the league,
where a click on a row opens that player in the Player tab.

Scope toggle: one season, or Career (every ingested season pooled - the
percentages are recomputed from summed makes/attempts, not averaged).
Every percentage is shown next to its attempt volume so low-volume
outliers (a center shooting 100% on three 3PA) are visible at a glance.

The Columns control picks one of three column sets. Basic and Shooting
read the player marts through data.players; Advanced adds the rate stats
from mart_player_season (data.advanced), and only exists in Season scope
for a season with complete box scores, in a warehouse that has the mart.

The filter box in Season scope looks in the selected season first; a player
who didn't play that season is still found, at his most recent season,
marked by a Season column (data.players.player_latest_seasons).
"""

from __future__ import annotations

from collections.abc import Sequence
from functools import partial
from typing import NamedTuple

import pandas as pd
import streamlit as st
from streamlit.delta_generator import DeltaGenerator

from core.constants import ADVANCED_STATS_FIRST_SEASON, COMPLETE_BOX_SCORE_FIRST_SEASON
from core.text import fold
from dashboard.lib import glossary
from dashboard.lib import theme as T
from dashboard.lib.advanced_metrics import PLAYER_COLUMN_CONFIG
from dashboard.lib.data import advanced, players, seasons
from dashboard.lib.state import SEASON_KEY
from dashboard.lib.stats import qualification_threshold
from dashboard.lib.widget_state import choice, hold_keys, selected_position
from dashboard.views.players.search import open_player

# The column sets, by the frame's column names. Career scope adds Yrs and
# Span after the team; a filter that reaches into other seasons adds a
# Season column after the name.
COLUMN_SETS = {
    "Basic": ["player", "team_label", "gp", "mpg", "ppg", "rpg", "apg", "spg", "bpg", "plus_minus"],
    "Shooting": [
        "player",
        "team_label",
        "gp",
        "ppg",
        "fg_pct",
        "fga_pg",
        "tpg",
        "tpa_pg",
        "fg3_pct",
        "ft_pct",
        "fta_pg",
        "ts_pct",
    ],
    "Advanced": [
        "player",
        "team_label",
        "gp",
        "mpg",
        "ppg",
        "ts_pct",
        "effective_fg_pct",
        "usage_pct",
        "assist_pct",
        "rebound_pct",
        "turnover_pct",
        "steal_pct",
        "block_pct",
        "game_score",
    ],
}
# The NBA's own figures, which exist only from ADVANCED_STATS_FIRST_SEASON.
OFFICIAL_COLS = ["net_rating", "player_impact_estimate"]
# What the Advanced set takes from mart_player_season. TS% and the box-score
# columns are already in the Players frame, so they are not taken twice.
MART_COLS = [
    "effective_fg_pct",
    "usage_pct",
    "assist_pct",
    "rebound_pct",
    "turnover_pct",
    "steal_pct",
    "block_pct",
    "game_score",
    *OFFICIAL_COLS,
]

# Session-state keys. The season box mirrors the sidebar's (SEASON_KEY).
PLAYERS_SEASON_KEY = "players_season"
PLAYERS_SEASON_ALL_KEY = "players_season_all"
PLAYERS_MIN_GP_KEY = "players_min_gp"
# The season the min-games slider was last reset for.
_MIN_GP_FOR_KEY = "players_min_gp_season"
SCOPE_KEY = "players_scope"
TEAM_KEY = "players_team"
MIN_CAREER_GP_KEY = "players_min_career_gp"
COLUMNS_KEY = "players_columns"
FILTER_KEY = "players_filter"
# The table's key is this plus the column set (table_key).
TABLE_KEY = "players_table"
# (player_id, season, career) for each row of the table as drawn, in order:
# a row click arrives as a position, and this turns it into a player.
TABLE_ROWS_KEY = "players_table_rows"

# The filter widgets, whose values keep_filters holds on to.
_FILTER_KEYS = [SCOPE_KEY, TEAM_KEY, PLAYERS_MIN_GP_KEY, MIN_CAREER_GP_KEY, COLUMNS_KEY, FILTER_KEY]


def keep_filters(also: Sequence[str] = ()) -> None:
    """Keep the filters as they were while another tab is open, and the
    widgets keyed in `also` (the Player tab's scope toggle and stat pickers)
    the same way (lib.widget_state.hold_keys). The page calls this on every
    run, before the active tab draws."""
    hold_keys([*_FILTER_KEYS, *also])


def table_key(columns: str) -> str:
    """The table's key for one column set ("players_table_shooting").

    One key per set, so switching sets draws a new grid rather than
    reshaping the old one. A reshaped grid ignores the first click on a
    cell after the switch (only its row checkbox still worked), so the
    reader's first click on a player did nothing."""
    return f"{TABLE_KEY}_{columns.lower().replace(' ', '_')}"


def reset_min_games(season: str) -> None:
    """Set the min-games slider to the season's qualification rule (25 games,
    fewer early in a live season) whenever the season changes, and leave the
    reader's own value after that. A fixed 25 empties the table for the
    first weeks of a season."""
    # Streamlit drops a widget's state on a run where it isn't rendered
    # (Career scope, or another page); the slider would come back at 1, so a
    # lost value resets too.
    if (
        st.session_state.get(_MIN_GP_FOR_KEY) != season
        or PLAYERS_MIN_GP_KEY not in st.session_state
    ):
        st.session_state[_MIN_GP_FOR_KEY] = season
        st.session_state[PLAYERS_MIN_GP_KEY] = qualification_threshold(
            players.player_season_stats(season)
        )


def lower_min_games(games: int) -> None:
    """Drop the min-games slider to `games` if it asks for more, so a player
    opened from elsewhere is in the table when the reader comes back to it."""
    if games < st.session_state[PLAYERS_MIN_GP_KEY]:
        st.session_state[PLAYERS_MIN_GP_KEY] = games


def _sync_season() -> None:
    """The page's season box drives the sidebar's, which every season-scoped
    page reads."""
    st.session_state[SEASON_KEY] = st.session_state[PLAYERS_SEASON_KEY]


class Filters(NamedTuple):
    """What the filter bar chose, with the stats it chose from."""

    career: bool
    stats: pd.DataFrame
    min_gp: int
    team: str
    search: str
    columns: str
    # Why the Advanced set isn't offered, or "" when it is.
    no_advanced: str


def _advanced_unavailable(career: bool, season: str) -> str:
    """Why the Advanced column set can't be shown, or "" when it can."""
    if career:
        return "Advanced stats are per season: switch Scope to Season to see them."
    if not advanced.marts_available():
        return "Advanced stats are not in this copy of the warehouse yet."
    if season not in advanced.advanced_seasons():
        return (
            f"Advanced stats start in {COMPLETE_BOX_SCORE_FIRST_SEASON}: earlier box "
            "scores are missing the rebounds, turnovers and shot attempts they need."
        )
    return ""


def _filter_bar(season: str, head: DeltaGenerator) -> Filters:
    """Title (into `head`, the page's container above the search, once the
    scope toggle is known), scope toggle, season / team / min-games /
    column-set / filter controls."""
    # The two segmented controls get the room their labels need; squeezed,
    # Streamlit cuts "Career" and "Advanced" off mid-word.
    f0, fs, f1, f2, fc, f3 = st.columns([3, 2, 2, 2, 5, 3], vertical_alignment="bottom")
    # required: a click on the chosen option keeps it, rather than clearing
    # the control and sending it back to its first option.
    career = choice(SCOPE_KEY, ["Season", "Career"]) == "Career"
    f0.segmented_control(
        "Scope", ["Season", "Career"], required=True, label_visibility="collapsed", key=SCOPE_KEY
    )

    if career:
        fs.selectbox(
            "Season",
            ["All seasons"],
            disabled=True,
            label_visibility="collapsed",
            key=PLAYERS_SEASON_ALL_KEY,
        )
    else:
        # Follow the sidebar, so the two boxes always show the same season.
        st.session_state[PLAYERS_SEASON_KEY] = season
        fs.selectbox(
            "Season",
            seasons.seasons(),
            key=PLAYERS_SEASON_KEY,
            label_visibility="collapsed",
            on_change=_sync_season,
            help="Same as the sidebar's season picker",
        )

    if career:
        stats = players.with_career_labels(players.player_career_stats())
        st.session_state.setdefault(MIN_CAREER_GP_KEY, 200)
        min_gp = f2.slider("Min career games", 1, 1500, key=MIN_CAREER_GP_KEY)
    else:
        stats = players.player_season_stats(season)
        # Keyed, so reset_min_games and a preset player (lower_min_games)
        # can set it; set before the slider rather than passed as its value,
        # which Streamlit would warn about alongside a value set through
        # session state.
        min_gp = f2.slider("Min games", 1, 82, key=PLAYERS_MIN_GP_KEY)

    with head:
        st.markdown(
            f"## Players &nbsp;"
            f"{T.chip('All seasons &middot; career totals' if career else season)}",
            unsafe_allow_html=True,
        )

    teams = ["All teams", *sorted(stats["team"].unique())]
    choice(TEAM_KEY, teams)
    team = f1.selectbox(
        "Team",
        teams,
        label_visibility="collapsed",
        help="Career scope: a player's most recent team",
        key=TEAM_KEY,
    )

    no_advanced = _advanced_unavailable(career, season)
    sets = [s for s in COLUMN_SETS if s != "Advanced" or not no_advanced]
    columns = choice(COLUMNS_KEY, sets)
    fc.segmented_control(
        "Columns",
        sets,
        required=True,
        label_visibility="collapsed",
        key=COLUMNS_KEY,
        help="Which stats the table shows",
    )

    search = f3.text_input(
        "Search", placeholder="Filter the table...", label_visibility="collapsed", key=FILTER_KEY
    )
    return Filters(career, stats, min_gp, team, search, columns, no_advanced)


def _filter_rows(f: Filters, season: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(rows to list, searched players who didn't play this season). The
    second frame is already appended to the first."""
    view = f.stats[f.stats.gp >= f.min_gp]
    if f.team != "All teams":
        # A traded player is listed under every team he played for.
        view = view[view.team_label.str.contains(f.team, regex=False)]
    if f.search:
        view = view[view.player.map(fold).str.contains(fold(f.search).strip(), regex=False)]
    view = view.sort_values("ppg", ascending=False)

    # Season scope: a searched player who didn't play this season shows at
    # his most recent season instead, after this season's matches.
    others = pd.DataFrame()
    if f.search.strip() and not f.career:
        others = players.player_latest_seasons(f.search, f.min_gp)
        others = others[~others.player_id.isin(view.player_id)]
        if f.team != "All teams":
            others = others[others.team_label.str.contains(f.team, regex=False)]
        others = others.sort_values("ppg", ascending=False)
    if not f.career:
        view = view.assign(season=season)
    if len(others):
        view = pd.concat([view, others], ignore_index=True)
    # Positions, not labels: a row click comes back as a position.
    return view.reset_index(drop=True), others


def _with_advanced(view: pd.DataFrame, season: str) -> tuple[pd.DataFrame, bool]:
    """`view` with the Advanced set's mart columns joined on player and
    season (a left join, so the filters above still decide the rows), and
    whether `season` has the official figures. A player the filter box
    found at another season gets that season's numbers, or blanks before
    COMPLETE_BOX_SCORE_FIRST_SEASON."""
    wanted = sorted(set(view["season"]) & set(advanced.advanced_seasons()))
    if not wanted:
        return view, False
    mart = pd.concat([advanced.player_advanced(s) for s in wanted], ignore_index=True)
    # An older warehouse may lack a column; it is left out, not an error.
    keep = [c for c in MART_COLS if c in mart.columns]
    merged = view.merge(
        mart[["player_id", "season", *keep]], on=["player_id", "season"], how="left"
    )
    official = mart.get("has_official_advanced")
    has_official = official is not None and bool(official[mart["season"] == season].any())
    return merged, has_official


def _column_config(ppg_max: float) -> dict:
    return {
        "player": st.column_config.TextColumn("Player", width="medium"),
        "team_label": st.column_config.TextColumn(
            "Team",
            width="small",
            help="Two teams (CHI → BOS) means traded mid-season; the line covers both",
        ),
        "seasons": st.column_config.NumberColumn("Yrs"),
        "season": st.column_config.TextColumn(
            "Season",
            width="small",
            help="Players who didn't play the selected season show their most recent one",
        ),
        "span": st.column_config.TextColumn("Span", width="medium"),
        "gp": st.column_config.NumberColumn(**glossary.described("GP")),
        "mpg": st.column_config.NumberColumn(**glossary.described("MIN"), format="%.1f"),
        "ppg": st.column_config.ProgressColumn(
            "PTS", format="%.1f", min_value=0, max_value=ppg_max, color=T.ACCENT, width="medium"
        ),
        "rpg": st.column_config.NumberColumn("REB", format="%.1f"),
        "apg": st.column_config.NumberColumn("AST", format="%.1f"),
        "spg": st.column_config.NumberColumn("STL", format="%.1f"),
        "bpg": st.column_config.NumberColumn("BLK", format="%.1f"),
        "fg_pct": st.column_config.NumberColumn(**glossary.described("FG%"), format="%.1f"),
        "fga_pg": st.column_config.NumberColumn(**glossary.described("FGA"), format="%.1f"),
        "tpg": st.column_config.NumberColumn(**glossary.described("3PM"), format="%.1f"),
        "tpa_pg": st.column_config.NumberColumn(**glossary.described("3PA"), format="%.1f"),
        "fg3_pct": st.column_config.NumberColumn(**glossary.described("3P%"), format="%.1f"),
        "ft_pct": st.column_config.NumberColumn(**glossary.described("FT%"), format="%.1f"),
        "fta_pg": st.column_config.NumberColumn(**glossary.described("FTA"), format="%.1f"),
        "ts_pct": st.column_config.NumberColumn(**glossary.marked("TS%"), format="%.1f"),
        "plus_minus": st.column_config.NumberColumn(**glossary.marked("+/-"), format="%.1f"),
    }


def _advanced_config(view: pd.DataFrame) -> dict:
    """The mart columns' formatting, with game score as the bar. Its floor
    tracks the data instead of assuming zero: game score goes negative for
    a bad season, and a 0 floor would render those as an empty bar
    indistinguishable from a replacement-level one."""
    scores = view["game_score"].dropna() if "game_score" in view else pd.Series(dtype=float)
    gs_min = float(min(0.0, scores.min())) if len(scores) else 0.0
    gs_max = float(scores.max()) if len(scores) else 1.0
    if gs_max <= gs_min:
        gs_max = gs_min + 1.0
    return {col: cfg for col, cfg in PLAYER_COLUMN_CONFIG.items() if col in MART_COLS} | {
        "game_score": st.column_config.ProgressColumn(
            **glossary.marked("GmSc"),
            format="%.1f",
            width="medium",
            min_value=gs_min,
            max_value=gs_max,
            color=T.ACCENT,
        ),
    }


def _on_select(key: str) -> None:
    """The table's on_select (`key` is the table's): open the clicked row's
    player (lib.widget_state.selected_position). A click that clears the
    selection opens nobody."""
    position = selected_position(key)
    if position is None:
        return
    row = st.session_state[TABLE_ROWS_KEY].iloc[position]
    open_player(int(row["player_id"]), str(row["season"]), career=bool(row["career"]))


def _stats_table(view: pd.DataFrame, others: pd.DataFrame, f: Filters, season: str) -> None:
    has_official = False
    if f.columns == "Advanced":
        view, has_official = _with_advanced(view, season)
    table_cols = COLUMN_SETS[f.columns] + (
        OFFICIAL_COLS if f.columns == "Advanced" and has_official else []
    )
    if f.career:
        table_cols[2:2] = ["seasons", "span"]
    elif len(others):
        table_cols[1:1] = ["season"]
    table_cols = [c for c in table_cols if c in view.columns]

    # Scale the PTS bar to the best scorer actually in view, so the column
    # still reads as a comparison after a search or a min-games filter
    # narrows the table. Guarded because an empty search result has no max.
    ppg_max = float(view["ppg"].max()) if len(view) and view["ppg"].notna().any() else 1.0
    column_config = _column_config(ppg_max)
    if f.columns != "Basic":
        # One bar per table: PTS in Basic, game score in Advanced.
        column_config["ppg"] = st.column_config.NumberColumn("PTS", format="%.1f")
    if f.columns == "Advanced":
        column_config |= _advanced_config(view)

    # What a click on each row opens: the player at the row's season, or
    # his career at his last season in Career scope.
    st.session_state[TABLE_ROWS_KEY] = pd.DataFrame(
        {
            "player_id": view["player_id"],
            "season": view["last_season"] if f.career else view["season"],
            "career": f.career,
        }
    )
    key = table_key(f.columns)
    st.dataframe(
        view[table_cols],
        hide_index=True,
        # About 15 rows, or just the rows there are: a short list (one team,
        # a search) would otherwise sit above a block of empty grid.
        height=min(600, (len(view) + 1) * 38 + 3),
        row_height=38,
        column_config=column_config,
        # st.dataframe takes no callback args, hence the partial.
        on_select=partial(_on_select, key),
        # Row selection alone only reacts to the checkbox at the left edge;
        # a click on a name selects that cell and nothing happens. Cell
        # selection too makes a click anywhere on the row open the player.
        selection_mode=["single-row", "single-cell"],
        key=key,
    )
    st.caption("Click a row to open that player. Click a column header to sort.")
    if f.no_advanced:
        st.caption(f.no_advanced)
    if f.career:
        st.caption(
            "Career view pools every ingested season (1979-80 onward) - "
            "the sidebar season selector does not apply here. Percentages "
            "are computed from career totals, shown next to attempt volume."
        )
        return
    if len(others):
        n = len(others)
        st.caption(
            f'{n} player{"s" if n > 1 else ""} matching "{f.search.strip()}" '
            f"didn't play {season}: shown at their most recent season "
            f"(the Season column), after {season}'s players."
        )
    if f.columns == "Shooting":
        st.caption(
            "Per-game averages; percentages are season totals, shown next to "
            "their attempt volume (FGA / 3PA / FTA)."
        )
    elif f.columns == "Advanced":
        st.caption(
            "Net rating and PIE are official NBA figures; everything else is "
            "computed from box scores."
            if has_official
            else "All metrics are computed from box scores. The NBA did not "
            f"publish official advanced stats until {ADVANCED_STATS_FIRST_SEASON}."
        )


def render_table(head: DeltaGenerator) -> pd.DataFrame | None:
    """The All players tab. `head` is the container the page title goes in.
    Returns the rows in view, best scorer first (the Player tab's default
    player), or None when the filters leave nobody."""
    season = st.session_state.get(SEASON_KEY) or seasons.latest_season()
    f = _filter_bar(season, head)
    view, others = _filter_rows(f, season)
    _stats_table(view, others, f, season)
    return view if len(view) else None
