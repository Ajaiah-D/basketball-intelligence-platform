"""The defense metrics the Player tab's Defense section ranks, and which
seasons each source covers.

Everything comes from mart_player_defense (data.players.player_defense).
Four metrics are better when lower (opponents shooting worse, fewer points
allowed); percentile_of reverses those, so a longer bar is always better.
"""

from __future__ import annotations

import pandas as pd

from core.constants import DEFENSE_TRACKING_FIRST_SEASON, HUSTLE_FIRST_SEASON
from dashboard.lib.stats import percentile_of

# Label -> (mart_player_defense column, higher_is_better), in bar order.
DEFENSE_METRICS: dict[str, tuple[str, bool]] = {
    "Opp FG% vs normal": ("d_fg_pct_diff", False),
    "Rim FG% allowed": ("rim_fg_pct", False),
    "Deflections/36": ("deflections_per_36", True),
    "Contested/36": ("contested_per_36", True),
    "Charges/36": ("charges_per_36", True),
    "Loose balls/36": ("loose_balls_per_36", True),
    "Box-outs/36": ("box_outs_per_36", True),
    "STL/36": ("steals_per_36", True),
    "BLK/36": ("blocks_per_36", True),
    "Def rating": ("on_court_def_rating", False),
    "On/off": ("def_on_minus_off", False),
}

LOWER_IS_BETTER = [label for label, (_, higher) in DEFENSE_METRICS.items() if not higher]


def defense_percentiles(row: pd.Series, pool: pd.DataFrame) -> list[tuple[str, float, float]]:
    """(label, percentile, raw value) for each defense metric the player has
    a value for and the pool can rank, in DEFENSE_METRICS order."""
    out: list[tuple[str, float, float]] = []
    for label, (col, higher_better) in DEFENSE_METRICS.items():
        if col not in pool.columns:
            continue
        value = row.get(col)
        if value is None or value != value:
            continue
        pct = percentile_of(pool[col], float(value), higher_better)
        if pct is not None:
            out.append((label, pct, float(value)))
    return out


def missing_sources(season: str) -> list[str]:
    """One line per tracking source that doesn't cover `season` yet."""
    year = int(season[:4])
    lines = []
    if year < int(DEFENSE_TRACKING_FIRST_SEASON[:4]):
        lines.append(f"Defender tracking starts in {DEFENSE_TRACKING_FIRST_SEASON}.")
    if year < int(HUSTLE_FIRST_SEASON[:4]):
        lines.append(f"Hustle stats start in {HUSTLE_FIRST_SEASON}.")
    return lines
