"""Small statistical rules the pages share: who qualifies for a leaderboard,
where a value ranks, and how well the model's probabilities are calibrated.
Pure pandas/numpy, no warehouse access."""

from __future__ import annotations

import numpy as np
import pandas as pd


def qualification_threshold(stats: pd.DataFrame, full_season: int = 25) -> int:
    """Minimum games to appear on a rate-stat leaderboard.

    A fixed cut empties every leaderboard for the first weeks of a live
    season (nobody has 25 games in November), so scale it to how far the
    season has actually run - the same idea as the NBA's "share of team
    games played" rule - and cap it at the full-season number.

    mart_player_percentiles repeats this rule in SQL (the qualification_games
    macro); change one and you must change the other.
    tests/test_player_percentiles.py asserts they agree.
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


# Below this many settled games a calibration bin holds a handful of games:
# noise, not calibration.
CALIBRATION_MIN_GAMES = 50
CALIBRATION_COLUMNS = ["bin_mid", "predicted_mean", "actual_rate", "n"]


def calibration_bins(settled: pd.DataFrame, bins: int = 10) -> pd.DataFrame:
    """Does "70%" mean 70%? Settled predictions (win_probability, home_won)
    bucketed by predicted home-win probability into equal-width bins on
    [0, 1]; per bin the mean predicted probability, the share the home team
    actually won, and the game count. Empty bins are dropped, and nothing is
    returned below CALIBRATION_MIN_GAMES games."""
    if len(settled) < CALIBRATION_MIN_GAMES:
        return pd.DataFrame(columns=CALIBRATION_COLUMNS)

    prob = settled["win_probability"].astype(float).to_numpy()
    won = settled["home_won"].astype(bool).astype(float).to_numpy()
    # p == 1.0 belongs in the top bin, not a phantom eleventh.
    idx = np.minimum((prob * bins).astype(int), bins - 1)
    frame = pd.DataFrame({"bin": idx, "p": prob, "won": won})
    out = (
        frame.groupby("bin")
        .agg(predicted_mean=("p", "mean"), actual_rate=("won", "mean"), n=("p", "size"))
        .reset_index()
    )
    out["bin_mid"] = (out["bin"] + 0.5) / bins
    return out[CALIBRATION_COLUMNS]
