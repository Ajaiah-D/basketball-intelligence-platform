"""Similar players: who, in the same season, has the statistical profile
closest to one player's. The same method as the soccer Scouting Hub's
similar-players search:

1. The pool is one season's players over a minutes floor (the caller
   passes it; the Players page uses advanced_metrics.minutes_floor), so a
   40-minute cameo with a freak shooting line can't match anyone.
2. Each FEATURES stat is z-scored over the pool: how many standard
   deviations above or below the pool's average. A stat any pool player
   lacks is left out for everyone, so every player is compared on the same
   stats rather than some on fewer.
3. Each z-score is capped at +/-Z_CAP, so one extreme stat (a shot-blocking
   center's block rate) can't decide a match on its own.
4. Cosine similarity between his capped z-scores and everyone else's: 1 is
   the same shape of profile, 0 unrelated, below 0 the opposite. He is left
   out of his own list.

Rates and shares rather than per-game totals, so a player is matched on how
he plays more than how long; minutes per game is one feature among twelve,
so a bench player with a starter's rates still ranks below a starter with
them. The warehouse has no positions, so position plays no part.

Pure pandas and numpy, no warehouse or Streamlit, so tests feed it frames.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import NamedTuple

import numpy as np
import pandas as pd

# mart_player_season column -> its short label, for the page's caption.
# Every one exists for every player-season with complete box scores
# (1985-86 on), official advanced figures or not.
FEATURES: dict[str, str] = {
    "minutes_per_game": "MIN",
    "points_per_36": "PTS/36",
    "usage_pct": "USG%",
    "true_shooting_pct": "TS%",
    "three_point_attempt_rate": "3PA rate",
    "free_throw_rate": "FT rate",
    "assist_pct": "AST%",
    "turnover_pct": "TOV%",
    "offensive_rebound_pct": "OREB%",
    "defensive_rebound_pct": "DREB%",
    "steal_pct": "STL%",
    "block_pct": "BLK%",
}

# No z-score counts for more than this many standard deviations.
Z_CAP = 3.0


class NotInPoolError(ValueError):
    """The player has no line in the season, or one under the minutes floor."""


class Similar(NamedTuple):
    """rank_similar's answer."""

    # The other players, most similar first: the pool's columns plus rank
    # (1, 2, ...) and similarity (cosine, -1 to 1).
    ranked: pd.DataFrame
    # The FEATURES columns the ranking used.
    features: list[str]
    # Players in the pool, him included.
    pool_size: int


def qualified(season: pd.DataFrame, min_minutes: int) -> pd.DataFrame:
    """The players in `season` (one row each, with a minutes column) who
    played at least `min_minutes`."""
    return season[season["minutes"] >= min_minutes]


def usable_features(pool: pd.DataFrame, features: Mapping[str, str] | list[str]) -> list[str]:
    """The `features` every player in `pool` has a value for, in order."""
    return [c for c in features if c in pool.columns and pool[c].notna().all()]


def capped_zscores(pool: pd.DataFrame, features: list[str], cap: float = Z_CAP) -> np.ndarray:
    """`pool`'s `features` as z-scores over the pool, each capped at +/-cap.
    A stat everyone shares (no spread) scores 0 for everyone."""
    x = pool[features].astype(float)
    spread = x.std(ddof=0).replace(0.0, 1.0)
    return ((x - x.mean()) / spread).clip(-cap, cap).to_numpy()


def cosine_to(target: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    """Cosine similarity of `target` with each row of `matrix`; 0 where
    either vector is all zeros (exactly average on every stat)."""
    norms = np.linalg.norm(matrix, axis=1) * np.linalg.norm(target)
    dots = matrix @ target
    return np.divide(dots, norms, out=np.zeros_like(dots, dtype=float), where=norms > 0)


def rank_similar(
    season: pd.DataFrame,
    player_id: int,
    min_minutes: int,
    n: int = 10,
    features: Mapping[str, str] | list[str] = FEATURES,
    cap: float = Z_CAP,
) -> Similar:
    """The `n` players in `season` (mart_player_season rows: player_id,
    minutes and the feature columns) most like `player_id`, among those
    with `min_minutes`+ minutes, z-scores capped at +/-`cap`. Ties go to
    the lower player_id, so the order is stable. Raises NotInPoolError when he
    isn't over the floor, and ValueError when no feature is usable or `n`
    is under 1."""
    if n < 1:
        raise ValueError("n must be at least 1")
    pool = qualified(season, min_minutes).reset_index(drop=True)
    is_him = pool["player_id"] == player_id
    if not is_him.any():
        raise NotInPoolError(f"player {player_id} has under {min_minutes} minutes or no line")
    used = usable_features(pool, features)
    if not used:
        raise ValueError("no feature has a value for every player in the pool")
    z = capped_zscores(pool, used, cap)
    scored = pool.assign(similarity=cosine_to(z[int(is_him.to_numpy().argmax())], z))
    ranked = (
        scored[~is_him]
        .sort_values(["similarity", "player_id"], ascending=[False, True])
        .head(n)
        .reset_index(drop=True)
    )
    ranked.insert(0, "rank", range(1, len(ranked) + 1))
    return Similar(ranked, used, len(pool))
