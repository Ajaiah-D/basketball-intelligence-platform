"""Small statistical rules the pages share: who qualifies for a leaderboard,
and where a value ranks. Pure pandas, no warehouse access."""

from __future__ import annotations

import pandas as pd


def qualification_threshold(stats: pd.DataFrame, full_season: int = 25) -> int:
    """Minimum games to appear on a rate-stat leaderboard.

    A fixed cut empties every leaderboard for the first weeks of a live
    season (nobody has 25 games in November), so scale it to how far the
    season has actually run - the same idea as the NBA's "share of team
    games played" rule - and cap it at the full-season number.
    """
    if stats.empty:
        return 0
    return max(1, min(full_season, int(stats["gp"].max() * 0.6)))


def percentile_of(series: pd.Series, value: float, higher_is_better: bool = True) -> float | None:
    """Where `value` sits in `series`, 0-100. Used to answer "is 36% from three
    good" with a rank instead of a bare league average."""
    clean = series.dropna()
    if not len(clean) or value != value:
        return None
    pct = (clean < value).sum() / len(clean) * 100
    return pct if higher_is_better else 100 - pct
