"""The advanced-metric tables the Players page draws on.

These used to live in the Advanced page's view. The page is gone (advanced
stats now sit on Players and Teams), but the metric list, the column
formatting and the minutes floor still need one home so the views do not
each restate them.

Rate stats need a minutes floor to mean anything (one made three-pointer on
the season is a 150% true shooting percentage), so anything ranked here is
measured against players over `minutes_floor`, not the whole league.
"""

import pandas as pd
import streamlit as st

from core.constants import ADVANCED_STATS_FIRST_SEASON
from dashboard.lib import glossary
from dashboard.lib.stats import percentile_of

# Percentile comparison uses metrics that exist for every complete season,
# so the head-to-head still works for pre-1997 players.
COMPARE_METRICS = ["TS%", "USG%", "AST%", "REB%", "STL%", "BLK%", "Game score"]

# Label -> (column, higher_is_better, help text). The metric list lives in
# one place instead of being restated per widget.
ADVANCED_METRICS: dict[str, tuple[str, bool, str]] = {
    "TS%": (
        "true_shooting_pct",
        True,
        "True shooting: points per shooting possession, counting 3s and free throws",
    ),
    "eFG%": (
        "effective_fg_pct",
        True,
        "Effective FG%: field goal percentage with 3-pointers weighted 1.5x",
    ),
    "USG%": (
        "usage_pct",
        True,
        "Usage: share of team possessions a player ends while on the floor",
    ),
    "AST%": (
        "assist_pct",
        True,
        "Assist rate: share of teammate field goals a player assisted while on the floor",
    ),
    "REB%": (
        "rebound_pct",
        True,
        "Rebound rate: share of available rebounds a player grabbed while on the floor",
    ),
    "TOV%": (
        "turnover_pct",
        False,
        "Turnover rate: turnovers per 100 individual plays (lower is better)",
    ),
    "STL%": ("steal_pct", True, "Steals per opponent possession while on the floor"),
    "BLK%": ("block_pct", True, "Share of opponent 2-point attempts blocked"),
    "PTS/36": ("points_per_36", True, "Points per 36 minutes, pace of a starter's night"),
    "PTS/100": ("points_per_100", True, "Points per 100 team possessions on the floor"),
    "Game score": (
        "game_score",
        True,
        "Hollinger game score: one-number box score summary, ~10 is average",
    ),
    "Net rating": (
        "net_rating",
        True,
        "Team point differential per 100 possessions with the player on the floor "
        f"(official NBA figure, {ADVANCED_STATS_FIRST_SEASON} on)",
    ),
    "PIE": (
        "player_impact_estimate",
        True,
        "Player impact estimate: share of the game's total production "
        f"(official NBA figure, {ADVANCED_STATS_FIRST_SEASON} on)",
    ),
}

# Column formatting for a table of mart_player_season rows, keyed by the
# mart's column names.
PLAYER_COLUMN_CONFIG = {
    "player_name": st.column_config.TextColumn("Player", width="medium"),
    "team_label": st.column_config.TextColumn(
        "Team",
        width="small",
        help="Two teams (CHI → BOS) means traded mid-season; the line covers both",
    ),
    "games_played": st.column_config.NumberColumn(**glossary.described("GP")),
    "minutes_per_game": st.column_config.NumberColumn(**glossary.described("MIN"), format="%.1f"),
    "points_per_game": st.column_config.NumberColumn("PTS", format="%.1f"),
    # Every rate metric is jargon to a casual fan: marked with an icon and
    # explained on header hover (dashboard/lib/glossary.py).
    **{
        col: st.column_config.NumberColumn(**glossary.marked(label), format="%.1f")
        for col, label in [
            ("true_shooting_pct", "TS%"),
            ("effective_fg_pct", "eFG%"),
            ("usage_pct", "USG%"),
            ("assist_pct", "AST%"),
            ("rebound_pct", "REB%"),
            ("game_score", "GmSc"),
            ("turnover_pct", "TOV%"),
            ("steal_pct", "STL%"),
            ("block_pct", "BLK%"),
            ("points_per_36", "P/36"),
            ("points_per_100", "P/100"),
            ("net_rating", "NET"),
            ("player_impact_estimate", "PIE"),
        ]
    },
}


def minutes_floor(stats: pd.DataFrame) -> int:
    """The minimum minutes for a rate stat to count. A rate stat on 40
    minutes is noise, so the floor scales with how much of the season has
    been played (30% of the busiest player's minutes) rather than sitting at
    a fixed number, within 50 to 500."""
    if stats.empty:
        return 50
    return min(500, max(50, int(stats["minutes"].max() * 0.3)))


def advanced_percentiles(row: pd.Series, pool: pd.DataFrame) -> list[tuple[str, float, float]]:
    """(label, percentile, raw value) for each comparison metric, ranking the
    player's value against `pool` (players over the minutes floor). A metric
    the player has no value for, or one the pool cannot rank, is skipped."""
    out: list[tuple[str, float, float]] = []
    for label in COMPARE_METRICS:
        col, higher_better, _ = ADVANCED_METRICS[label]
        value = row.get(col)
        if value is None or value != value:
            continue
        pct = percentile_of(pool[col], value, higher_better)
        if pct is not None:
            out.append((label, pct, value))
    return out
