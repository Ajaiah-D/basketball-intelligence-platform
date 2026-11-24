"""Similar players: who, in the same season, plays most like one player.

The question is "plays like", not "plays as well as". So a player's profile
is split into blocks, each about one part of how he plays, and each block
carries a weight that says how much it decides a match:

  Shot diet   where his shots come from: the share of his attempts at the
              rim, in the paint, from mid-range, the corner three and
              above the break, plus three-point volume and trips to the line
  Play type   how he gets them: the share of his possessions in isolation,
              transition, pick-and-roll (handling or rolling), post-ups,
              spot-ups, handoffs, cuts, off screens and putbacks
  Creation    how much he makes for others, by passing and by screening,
              and how often he gives it away
  Rebounding  how much of the glass he takes, plus a little of his height
  Defense     what kind of defender the numbers say he is: steals, blocks,
              how much of what he guards is at the rim, how active he is
  Role        how big his job is: minutes, usage, points, efficiency

Shot diet and Play type together are what Scoring used to be (box-score
three-point and free-throw rates, weight 3), with the same weight: they
describe how a player scores, so two players who score the same amount in
different ways no longer look alike. Play types start in 2015-16 and shot
zones in 1996-97; an earlier season simply goes without them (step 3).

Role weighs least. A model that weighs role heavily matches every
high-usage star with every other one, because stars all differ from the
average player in the same way (the first version's flaw: its minutes,
points, usage and assist stats decided most of every star's matches).

The method:

1. The pool is one season's players over a minutes floor (the caller
   passes it; the Players page uses advanced_metrics.minutes_floor), so a
   40-minute cameo with a freak shooting line can't match anyone.
2. A play-type share from a small sample is pulled toward the pool's
   average: (share * possessions + PLAY_TYPE_PRIOR * average) /
   (possessions + PLAY_TYPE_PRIOR). The prior is 100 possessions, ten for
   each of the ten play types, the same 10 a play type needs before the
   NBA lists it at all. Early in a season, with a low minutes floor, a
   handful of possessions would otherwise decide a player's whole style.
3. Each feature is z-scored over the pool and capped at +/-Z_CAP, so one
   extreme stat can't decide a match on its own. A feature most of the pool
   has (MIN_COVERAGE) is used, and a player without it counts as average on
   it; one the season lacks (tracking defense before 2013-14) is left out
   for everyone, and so is a block with no feature left.
4. Each feature's weight is its block's weight split across the block's
   features (by the feature's own weight within the block), so a block
   counts the same however many stats it holds: four overlapping stats
   don't count four times.
5. The distance between two players is the weighted Euclidean distance of
   their z-scores. Unlike cosine similarity it sees how far apart two
   players are, not only whether they lean the same way.
6. The match score is 100 * (1 - distance / the pool's median distance from
   him), floored at 0: 100 is the same profile, 0 is as different as a
   typical player in the pool. Each block gets the same score on its own,
   so the page can show where a match is close and where it isn't.

Positions play no part. Height is in, with a small weight, because the
stats only partly show the size a player works with.

Pure pandas and numpy, no warehouse or Streamlit, so tests feed it frames.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import NamedTuple

import numpy as np
import pandas as pd


class Block(NamedTuple):
    """One part of a profile: its name, its weight in a match, and its
    features (column -> weight within the block)."""

    name: str
    weight: float
    features: dict[str, float]


# The play-type shares (mart_player_scoring), shrunk by shrink_play_types.
# Misc is left out: it is what Synergy can't file anywhere else.
PLAY_TYPE_FEATURES: tuple[str, ...] = (
    "isolation_share",
    "transition_share",
    "pnr_handler_share",
    "pnr_roll_share",
    "post_up_share",
    "spot_up_share",
    "handoff_share",
    "cut_share",
    "off_screen_share",
    "putback_share",
)

BLOCKS: tuple[Block, ...] = (
    Block(
        "Shot diet",
        1.5,
        {
            "restricted_area_share": 1.0,
            "paint_share": 1.0,
            "mid_range_share": 1.0,
            "corner_three_share": 1.0,
            "above_break_three_share": 1.0,
            "threes_per_36": 1.0,
            "free_throw_rate": 1.0,
        },
    ),
    Block("Play type", 1.5, dict.fromkeys(PLAY_TYPE_FEATURES, 1.0)),
    Block(
        "Creation",
        2.0,
        {"assist_pct": 1.0, "turnover_pct": 1.0, "screen_assists_per_36": 1.0},
    ),
    Block(
        "Rebounding",
        1.5,
        {"offensive_rebound_pct": 1.0, "defensive_rebound_pct": 1.0, "height_inches": 0.5},
    ),
    Block(
        "Defense",
        1.5,
        {
            "steal_pct": 1.0,
            "block_pct": 1.0,
            "rim_share": 1.0,
            "fouls_per_36": 0.5,
            "contests_per_36": 0.5,
            "deflections_per_36": 0.5,
        },
    ),
    Block(
        "Role",
        1.0,
        {
            "minutes_per_game": 1.0,
            "usage_pct": 1.0,
            "points_per_36": 1.0,
            "true_shooting_pct": 1.0,
        },
    ),
)

# Each feature's short label, for the page's caption.
FEATURE_LABELS: dict[str, str] = {
    "restricted_area_share": "share of shots at the rim",
    "paint_share": "in the paint",
    "mid_range_share": "mid-range",
    "corner_three_share": "corner 3",
    "above_break_three_share": "above-the-break 3",
    "threes_per_36": "3PA/36",
    "free_throw_rate": "FT rate",
    "isolation_share": "isolation",
    "transition_share": "transition",
    "pnr_handler_share": "pick-and-roll handler",
    "pnr_roll_share": "roll man",
    "post_up_share": "post-up",
    "spot_up_share": "spot-up",
    "handoff_share": "handoff",
    "cut_share": "cut",
    "off_screen_share": "off screen",
    "putback_share": "putback",
    "assist_pct": "AST%",
    "turnover_pct": "TOV%",
    "screen_assists_per_36": "screen assists/36",
    "offensive_rebound_pct": "OREB%",
    "defensive_rebound_pct": "DREB%",
    "height_inches": "height",
    "steal_pct": "STL%",
    "block_pct": "BLK%",
    "rim_share": "share of shots defended at the rim",
    "fouls_per_36": "fouls/36",
    "contests_per_36": "contests/36",
    "deflections_per_36": "deflections/36",
    "minutes_per_game": "MIN",
    "usage_pct": "USG%",
    "points_per_36": "PTS/36",
    "true_shooting_pct": "TS%",
}

# No z-score counts for more than this many standard deviations.
Z_CAP = 3.0
# A feature is used when at least this share of the pool has it.
MIN_COVERAGE = 0.9
# How many possessions of the pool's average a play-type share is mixed
# with (see the module docstring): 10 for each play type.
PLAY_TYPE_PRIOR = 100.0


class NotInPoolError(ValueError):
    """The player has no line in the season, or one under the minutes floor."""


class Embedding(NamedTuple):
    """A pool as weighted, capped z-scores: the Euclidean distance between
    two rows is their match distance."""

    # One row per player, one column per feature, in `features` order.
    matrix: np.ndarray
    player_ids: np.ndarray
    features: list[str]
    # Each feature's block name, in `features` order.
    feature_blocks: list[str]


class Similar(NamedTuple):
    """rank_similar's answer."""

    # The other players, most similar first: the pool's columns plus rank
    # (1, 2, ...), distance, similarity (the match score, 0 to 100) and one
    # block_column(block) score per block used.
    ranked: pd.DataFrame
    # The features the ranking used.
    features: list[str]
    # The blocks the ranking used, in BLOCKS order.
    blocks: list[str]
    # Players in the pool, him included.
    pool_size: int


def block_column(block: str) -> str:
    """The ranked frame's column for one block's match score."""
    return f"{block.lower().replace(' ', '_')}_match"


def qualified(season: pd.DataFrame, min_minutes: int) -> pd.DataFrame:
    """The players in `season` (one row each, with a minutes column) who
    played at least `min_minutes`."""
    return season[season["minutes"] >= min_minutes]


def usable_features(pool: pd.DataFrame, features: Sequence[str]) -> list[str]:
    """The `features` at least MIN_COVERAGE of `pool` has, in order."""
    if pool.empty:
        return []
    return [c for c in features if c in pool.columns and pool[c].notna().mean() >= MIN_COVERAGE]


def shrink_play_types(pool: pd.DataFrame, prior: float = PLAY_TYPE_PRIOR) -> pd.DataFrame:
    """`pool` with each PLAY_TYPE_FEATURES share pulled toward the pool's
    average by `prior` possessions of it, against his play_type_possessions:
    a small sample moves a lot, a full season hardly at all. A player
    without play types stays without. Unchanged when `prior` is 0 or the
    pool has no possession counts."""
    if prior <= 0 or "play_type_possessions" not in pool.columns:
        return pool
    out = pool.copy()
    n = out["play_type_possessions"].astype(float)
    for f in PLAY_TYPE_FEATURES:
        if f in out.columns:
            share = out[f].astype(float)
            out[f] = (share * n + prior * share.mean()) / (n + prior)
    return out


def capped_zscores(pool: pd.DataFrame, features: list[str], cap: float = Z_CAP) -> np.ndarray:
    """`pool`'s `features` as z-scores over the pool, each capped at +/-cap.
    A stat everyone shares (no spread) scores 0 for everyone, and so does a
    player without the stat."""
    x = pool[features].astype(float)
    spread = x.std(ddof=0).replace(0.0, 1.0).fillna(1.0)
    return ((x - x.mean()) / spread).clip(-cap, cap).fillna(0.0).to_numpy()


def feature_weights(
    used: Sequence[str], blocks: Sequence[Block] = BLOCKS
) -> tuple[list[str], list[str], np.ndarray]:
    """(features, their blocks, their weights) for the `used` features, in
    block order: each block's weight split over its used features in
    proportion to their weights within the block."""
    used_set = set(used)
    features: list[str] = []
    names: list[str] = []
    weights: list[float] = []
    for block in blocks:
        mine = {f: w for f, w in block.features.items() if f in used_set}
        total = sum(mine.values())
        for f, w in mine.items():
            features.append(f)
            names.append(block.name)
            weights.append(block.weight * w / total)
    return features, names, np.array(weights, dtype=float)


def embed(
    pool: pd.DataFrame,
    blocks: Sequence[Block] = BLOCKS,
    only: Sequence[str] | None = None,
    cap: float = Z_CAP,
    prior: float = PLAY_TYPE_PRIOR,
) -> Embedding:
    """`pool` as an Embedding: its usable block features (or only those in
    `only`, e.g. the features two seasons share), play types shrunk by
    `prior`, z-scored over the pool, capped, and scaled by the square root
    of their weights. Raises ValueError when no feature is usable."""
    wanted = [f for b in blocks for f in b.features]
    if only is not None:
        wanted = [f for f in wanted if f in set(only)]
    features, names, weights = feature_weights(usable_features(pool, wanted), blocks)
    if not features:
        raise ValueError("no feature has a value for enough of the pool")
    z = capped_zscores(shrink_play_types(pool, prior), features, cap)
    return Embedding(z * np.sqrt(weights), pool["player_id"].to_numpy(), features, names)


def match_scores(distances: np.ndarray) -> np.ndarray:
    """Distances from one player to the others, as 0-100 match scores
    against their median: 100 at no distance, 0 at the median or beyond."""
    if not len(distances):
        return distances.astype(float)
    median = float(np.median(distances))
    if median <= 0:
        return np.where(distances <= 0, 100.0, 0.0)
    return np.clip(100.0 * (1.0 - distances / median), 0.0, 100.0)


def rank_similar(
    season: pd.DataFrame,
    player_id: int,
    min_minutes: int,
    n: int = 10,
    blocks: Sequence[Block] = BLOCKS,
    cap: float = Z_CAP,
) -> Similar:
    """The `n` players in `season` (rows with player_id, minutes and the
    block features) most like `player_id`, among those with `min_minutes`+
    minutes. Ties go to the lower player_id, so the order is stable. Raises
    NotInPoolError when he isn't over the floor, and ValueError when no
    feature is usable or `n` is under 1."""
    if n < 1:
        raise ValueError("n must be at least 1")
    pool = qualified(season, min_minutes).reset_index(drop=True)
    is_him = (pool["player_id"] == player_id).to_numpy()
    if not is_him.any():
        raise NotInPoolError(f"player {player_id} has under {min_minutes} minutes or no line")
    emb = embed(pool, blocks, cap=cap)
    diff = (emb.matrix - emb.matrix[int(is_him.argmax())])[~is_him]
    distance = np.sqrt((diff**2).sum(axis=1))

    others = pool[~is_him].assign(distance=distance, similarity=match_scores(distance))
    used_blocks = [b.name for b in blocks if b.name in emb.feature_blocks]
    for name in used_blocks:
        cols = [i for i, b in enumerate(emb.feature_blocks) if b == name]
        others[block_column(name)] = match_scores(np.sqrt((diff[:, cols] ** 2).sum(axis=1)))

    ranked = others.sort_values(["distance", "player_id"]).head(n).reset_index(drop=True)
    ranked.insert(0, "rank", range(1, len(ranked) + 1))
    return Similar(ranked, emb.features, used_blocks, len(pool))
