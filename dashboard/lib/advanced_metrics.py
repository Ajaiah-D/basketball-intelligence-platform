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

from dashboard.lib import glossary
from dashboard.lib.stats import percentile_of

# The metrics the Player tab's Advanced section ranks as percentiles. Each
# exists for every season with complete box scores, so a pre-1997 player
# (before the NBA's official figures) still gets a full profile.
COMPARE_METRICS = ["TS%", "USG%", "AST%", "REB%", "STL%", "BLK%", "Game score"]

# Label -> (mart_player_season column, higher_is_better) for each
# COMPARE_METRICS label.
ADVANCED_METRICS: dict[str, tuple[str, bool]] = {
    "TS%": ("true_shooting_pct", True),
    "USG%": ("usage_pct", True),
    "AST%": ("assist_pct", True),
    "REB%": ("rebound_pct", True),
    "STL%": ("steal_pct", True),
    "BLK%": ("block_pct", True),
    "Game score": ("game_score", True),
}

# Column formatting for the All players table's Advanced set, keyed by the
# mart_player_season columns it takes (MART_COLS in views/players/table.py).
# Game score is not here: the table draws it as a bar scaled to the rows in
# view. Every rate metric is jargon to a casual fan: marked with an icon and
# explained on header hover (dashboard/lib/glossary.py).
PLAYER_COLUMN_CONFIG = {
    col: st.column_config.NumberColumn(**glossary.marked(label), format="%.1f")
    for col, label in [
        ("effective_fg_pct", "eFG%"),
        ("usage_pct", "USG%"),
        ("assist_pct", "AST%"),
        ("rebound_pct", "REB%"),
        ("turnover_pct", "TOV%"),
        ("steal_pct", "STL%"),
        ("block_pct", "BLK%"),
        ("net_rating", "NET"),
        ("player_impact_estimate", "PIE"),
    ]
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
        col, higher_better = ADVANCED_METRICS[label]
        value = row.get(col)
        if value is None or value != value:
            continue
        pct = percentile_of(pool[col], value, higher_better)
        if pct is not None:
            out.append((label, pct, value))
    return out
