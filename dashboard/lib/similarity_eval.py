"""How good is a similar-players model? There is no list of right answers,
so this measures one thing that has to hold for any model of how a player
plays: a player's style carries over from one season to the next.

The self-match test hides who is who. Each player's season-one profile is
compared with every player's season-two profile, and the test records where
his own season two ranks (1 = the closest). The more players find
themselves near the top, the more the model captures how a player plays
rather than noise. Both seasons are z-scored over their own pools, as the
page does, on the features the two seasons share.

The test rewards stable stats, so it can't pick weights alone: height never
changes and would win it outright, and role size (minutes, usage) is
stable too. scripts/evaluate_similarity.py runs it with and without those
and adds a sanity panel of named players to read by eye.

Self-match can't see a wrong neighbour: a player can find himself first
and still have the wrong players around him. The known-pairs check covers
that: pairs of players who play the same way (one should rank in the
other's top MATCH_TOP) and pairs who only share box-score output (one
should rank outside the other's top AVOID_TOP). The pairs are judgement
calls, so they count beside self-match, never instead of it: tuning to
them alone would fit the model to our opinions.

LEGACY is the first version (twelve box-score rates, capped z-scores,
cosine similarity), kept here only as the baseline to beat, and
BEFORE_SHOT_DATA the block model as it was before the shot diet and play
types replaced its box-score Scoring block.

Pure pandas and numpy, like lib.similarity.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import NamedTuple

import numpy as np
import pandas as pd

from dashboard.lib import similarity as S

# The first version's features, all weighted the same.
LEGACY_FEATURES = [
    "minutes_per_game",
    "points_per_36",
    "usage_pct",
    "true_shooting_pct",
    "three_point_attempt_rate",
    "free_throw_rate",
    "assist_pct",
    "turnover_pct",
    "offensive_rebound_pct",
    "defensive_rebound_pct",
    "steal_pct",
    "block_pct",
]


class Model(NamedTuple):
    """A model to test: how it turns a pool into vectors (optionally only
    on the given features), and how it compares two vectors."""

    name: str
    embed: Callable[[pd.DataFrame, Sequence[str] | None], S.Embedding]
    # "cosine" (higher is closer) or "euclidean" (lower is closer).
    metric: str


def _legacy_embed(pool: pd.DataFrame, only: Sequence[str] | None = None) -> S.Embedding:
    """The first version: capped z-scores of LEGACY_FEATURES every player
    has, unweighted."""
    wanted = [f for f in LEGACY_FEATURES if only is None or f in set(only)]
    used = [f for f in wanted if f in pool.columns and pool[f].notna().all()]
    if not used:
        raise ValueError("no legacy feature has a value for every player")
    z = S.capped_zscores(pool, used)
    return S.Embedding(z, pool["player_id"].to_numpy(), used, ["Legacy"] * len(used))


LEGACY = Model("First version (cosine, 12 rates)", _legacy_embed, "cosine")


# The blocks before shot data: Scoring was three box-score rates.
BEFORE_SHOT_DATA: tuple[S.Block, ...] = (
    S.Block(
        "Scoring",
        3.0,
        {"three_point_attempt_rate": 1.0, "threes_per_36": 1.0, "free_throw_rate": 1.0},
    ),
    *(b for b in S.BLOCKS if b.name not in ("Shot diet", "Play type")),
)


def block_model(
    name: str, blocks: Sequence[S.Block] = S.BLOCKS, prior: float = S.PLAY_TYPE_PRIOR
) -> Model:
    """A Model for lib.similarity's method with `blocks` and play types
    shrunk by `prior` possessions (0 for none)."""

    def embed(pool: pd.DataFrame, only: Sequence[str] | None = None) -> S.Embedding:
        return S.embed(pool, blocks, only, prior=prior)

    return Model(name, embed, "euclidean")


def without(features: Sequence[str] = (), blocks: Sequence[str] = ()) -> tuple[S.Block, ...]:
    """S.BLOCKS less the named features and blocks (a block left empty
    goes too)."""
    out = []
    for b in S.BLOCKS:
        kept = {f: w for f, w in b.features.items() if f not in features}
        if b.name not in blocks and kept:
            out.append(S.Block(b.name, b.weight, kept))
    return tuple(out)


def closeness(a: np.ndarray, b: np.ndarray, metric: str) -> np.ndarray:
    """A len(a) x len(b) matrix where higher is closer: cosine similarity,
    or minus the Euclidean distance."""
    if metric == "cosine":
        norms = np.linalg.norm(a, axis=1)[:, None] * np.linalg.norm(b, axis=1)[None, :]
        return np.divide(a @ b.T, norms, out=np.zeros((len(a), len(b))), where=norms > 0)
    if metric == "euclidean":
        sq = (a**2).sum(axis=1)[:, None] + (b**2).sum(axis=1)[None, :] - 2 * a @ b.T
        return -np.sqrt(np.clip(sq, 0.0, None))
    raise ValueError(f"unknown metric {metric!r}")


def self_match(first: pd.DataFrame, second: pd.DataFrame, model: Model) -> pd.DataFrame:
    """For each player in both pools: player_id and the rank (1 = closest)
    of his own `second` profile among every `second` profile, compared with
    his `first` one. Ties count against him."""
    shared = sorted(
        set(model.embed(first, None).features) & set(model.embed(second, None).features)
    )
    a, b = model.embed(first, shared), model.embed(second, shared)
    both = np.intersect1d(a.player_ids, b.player_ids)
    row_of = {pid: i for i, pid in enumerate(a.player_ids)}
    col_of = {pid: i for i, pid in enumerate(b.player_ids)}
    rows = np.array([row_of[pid] for pid in both], dtype=int)
    cols = np.array([col_of[pid] for pid in both], dtype=int)
    scores = closeness(a.matrix[rows], b.matrix, model.metric)
    own = scores[np.arange(len(both)), cols]
    # Rank 1 + everyone strictly closer + anyone else exactly as close.
    better = (scores > own[:, None]).sum(axis=1)
    ties = (scores == own[:, None]).sum(axis=1) - 1
    return pd.DataFrame({"player_id": both, "rank": 1 + better + ties})


class Summary(NamedTuple):
    """One model's self-match result over one pair of seasons."""

    players: int
    candidates: int
    top1: float
    top5: float
    median_rank: float


def summarize(ranks: pd.DataFrame, candidates: int) -> Summary:
    """The share of players who found themselves first and in the top five,
    and the median rank."""
    r = ranks["rank"]
    return Summary(
        len(r), candidates, float((r == 1).mean()), float((r <= 5).mean()), float(r.median())
    )


# A "should match" pair holds when the other player ranks this high or
# better; a "should not" pair when he ranks below AVOID_TOP.
MATCH_TOP = 5
AVOID_TOP = 10


class Pair(NamedTuple):
    """On `player`'s list, where `other` should (or should not) be."""

    player: str
    other: str
    should_match: bool
    why: str


def rank_of(pool: pd.DataFrame, model: Model, player_id: int, other_id: int) -> int:
    """Where `other_id` ranks (1 = closest) among everyone else in `pool`,
    compared with `player_id` under `model`. Ties count against the pair."""
    emb = model.embed(pool, None)
    ids = list(emb.player_ids)
    for pid in (player_id, other_id):
        if pid not in ids:
            raise S.NotInPoolError(f"player {pid} is not in the pool")
    me, them = ids.index(player_id), ids.index(other_id)
    scores = closeness(emb.matrix[[me]], emb.matrix, model.metric)[0]
    others = np.delete(scores, me)
    # Rank 1 + everyone strictly closer + anyone else exactly as close.
    return int(1 + (others > scores[them]).sum() + (others == scores[them]).sum() - 1)


def pair_holds(pair: Pair, rank: int) -> bool:
    """Whether a pair's rank is where the pair says it should be."""
    return rank <= MATCH_TOP if pair.should_match else rank > AVOID_TOP
