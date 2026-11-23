"""dashboard/lib/similarity.py: the Similar players ranking, on synthetic
pools (no warehouse), plus sanity checks on the real one."""

import numpy as np
import pandas as pd
import pytest

from dashboard.lib import similarity as S
from dashboard.lib.advanced_metrics import minutes_floor
from dashboard.lib.data import advanced, seasons

# Two blocks for the synthetic pools: "Style" (a, b) weighs 3, "Size" (c) 1.
BLOCKS = (S.Block("Style", 3.0, {"a": 1.0, "b": 1.0}), S.Block("Size", 1.0, {"c": 1.0}))
FEATURES = ["a", "b", "c"]


def _pool(rows: list[tuple[int, int, float, float, float]]) -> pd.DataFrame:
    """(player_id, minutes, a, b, c) rows."""
    return pd.DataFrame(rows, columns=["player_id", "minutes", *FEATURES])


# Player 1's profile; 3 is close; 2 leans the same way as 1 but further from
# the average; 4 is the mirror image; 5 is a 10-minute cameo with exactly
# 1's numbers.
POOL = _pool(
    [
        (1, 900, 6.0, 4.0, 5.0),
        (2, 900, 7.0, 3.0, 6.0),
        (3, 900, 6.0, 4.5, 5.0),
        (4, 900, 0.0, 8.0, 1.0),
        (5, 10, 6.0, 4.0, 5.0),
        (6, 900, 3.0, 6.0, 3.0),
        (7, 900, 4.0, 5.0, 4.0),
    ]
)


def _rank(pool: pd.DataFrame, player_id: int = 1, floor: int = 100, n: int = 10) -> S.Similar:
    return S.rank_similar(pool, player_id, floor, n, blocks=BLOCKS)


def test_the_closest_profile_ranks_first_and_the_opposite_last():
    result = _rank(POOL)
    ids = list(result.ranked["player_id"])
    assert ids[0] == 3
    assert ids[-1] == 4
    assert result.ranked["distance"].is_monotonic_increasing
    assert result.ranked["similarity"].is_monotonic_decreasing
    assert list(result.ranked["rank"]) == list(range(1, len(ids) + 1))


def test_distance_sees_how_far_apart_not_only_the_direction():
    # 2 leans the same way as 1 from the average, only further: cosine
    # would call them alike, distance puts 3 (truly close) ahead.
    ids = list(_rank(POOL).ranked["player_id"])
    assert ids.index(3) < ids.index(2)


def test_scores_run_from_100_for_the_same_profile_to_0_for_a_typical_player():
    loose = _rank(POOL, floor=0)
    # 5 has exactly 1's numbers.
    assert loose.ranked["player_id"].iloc[0] == 5
    assert loose.ranked["similarity"].iloc[0] == pytest.approx(100.0)
    assert loose.ranked["similarity"].between(0, 100).all()
    assert (loose.ranked["similarity"] == 0).any()  # the median and beyond


def test_each_block_gets_its_own_score():
    result = _rank(POOL)
    assert result.blocks == ["Style", "Size"]
    for name in result.blocks:
        assert result.ranked[S.block_column(name)].between(0, 100).all()
    # 3 matches 1's size exactly.
    three = result.ranked.set_index("player_id").loc[3]
    assert three[S.block_column("Size")] == pytest.approx(100.0)


def test_he_is_not_on_his_own_list():
    assert 1 not in set(_rank(POOL).ranked["player_id"])


def test_players_under_the_minutes_floor_are_left_out():
    result = _rank(POOL)
    assert 5 not in set(result.ranked["player_id"])
    assert result.pool_size == 6


def test_a_player_under_the_floor_has_no_list():
    with pytest.raises(S.NotInPoolError):
        _rank(POOL, player_id=5)
    with pytest.raises(S.NotInPoolError):
        _rank(POOL, player_id=99, floor=0)


def test_the_list_is_as_long_as_asked_or_the_pool_allows():
    pool = _pool([(i, 900, float(i), float(i % 3), float(i % 5)) for i in range(1, 41)])
    for n in (5, 10, 25):
        assert len(_rank(pool, floor=0, n=n).ranked) == n
    assert len(_rank(POOL, n=25).ranked) == 5
    with pytest.raises(ValueError):
        _rank(POOL, n=0)


def test_z_scores_are_capped():
    # One huge outlier in `a`: uncapped it would sit near +4.4 sd.
    pool = _pool([(i, 900, 1.0, float(i), 0.0) for i in range(1, 21)] + [(99, 900, 1000.0, 5, 0)])
    z = S.capped_zscores(pool, FEATURES)
    assert z.max() == pytest.approx(S.Z_CAP)
    assert np.abs(z).max() <= S.Z_CAP
    # A stat with no spread scores 0 for everyone instead of dividing by zero.
    assert (z[:, 2] == 0).all()


def test_a_block_counts_by_its_weight_however_many_stats_it_holds():
    # Four stats in one block, one in another, same weight: each block's
    # weights sum to its block weight.
    blocks = (
        S.Block("Many", 2.0, {"a": 1.0, "b": 1.0, "c": 1.0, "d": 1.0}),
        S.Block("One", 2.0, {"e": 1.0}),
    )
    features, names, weights = S.feature_weights(["a", "b", "c", "d", "e"], blocks)
    assert features == ["a", "b", "c", "d", "e"]
    assert names == ["Many"] * 4 + ["One"]
    assert weights[:4].sum() == pytest.approx(2.0)
    assert weights[4] == pytest.approx(2.0)


def test_a_feature_weight_within_a_block_splits_its_weight():
    blocks = (S.Block("B", 3.0, {"a": 1.0, "h": 0.5}),)
    _, _, weights = S.feature_weights(["a", "h"], blocks)
    assert list(weights) == pytest.approx([2.0, 1.0])
    # Without `h` the block's whole weight goes to `a`.
    assert list(S.feature_weights(["a"], blocks)[2]) == pytest.approx([3.0])


def test_the_heavier_block_decides_the_match():
    # 3 matches 1 on style and differs only on size (c); 2 matches his size
    # and differs on one style stat (a), by the same amount: a and c have
    # the same spread. With equal weights it's a tie, which goes to the
    # lower id, 2; Style weighing 3 makes the style match, 3, the closer.
    values = [-2.0, -1.0, 0.0, 1.0, 2.0] * 4
    filler = [(10 + i, 900, v, 4.0 + i % 3, v) for i, v in enumerate(values)]
    pool = _pool([(1, 900, 1.0, 1.0, 1.0), (2, 900, -1.0, 1.0, 1.0), (3, 900, 1.0, 1.0, -1.0)])
    pool = pd.concat([pool, _pool(filler)], ignore_index=True)

    def first(blocks: tuple[S.Block, ...]) -> int:
        return int(S.rank_similar(pool, 1, 0, 1, blocks=blocks).ranked["player_id"].iloc[0])

    even = (S.Block("Style", 1.0, {"a": 1.0, "b": 1.0}), S.Block("Size", 0.5, {"c": 1.0}))
    assert first(even) == 2
    assert first(BLOCKS) == 3


def test_a_stat_most_players_have_counts_and_the_rest_count_as_average():
    rows = [(i, 900, float(i), float(i % 4), float(i % 3)) for i in range(1, 21)]
    pool = _pool(rows).assign(d=[None, *range(2, 21)])  # 19 of 20 = 95%
    blocks = (*BLOCKS, S.Block("Extra", 1.0, {"d": 1.0}))
    assert S.rank_similar(pool, 1, 0, blocks=blocks).features == [*FEATURES, "d"]
    assert S.capped_zscores(pool, ["d"])[0, 0] == 0.0
    # Under MIN_COVERAGE the stat and its block are left out for everyone.
    sparse = pool.assign(d=[None] * 5 + list(range(6, 21)))
    result = S.rank_similar(sparse, 1, 0, blocks=blocks)
    assert result.features == FEATURES
    assert result.blocks == ["Style", "Size"]


def test_no_usable_feature_is_an_error():
    with pytest.raises(ValueError):
        _rank(POOL.drop(columns=FEATURES))


def test_ties_break_on_player_id():
    pool = _pool([(1, 900, 1.0, 0.0, 0.0), (7, 900, 1.0, 0.0, 0.0), (3, 900, 1.0, 0.0, 0.0)])
    pool = pd.concat([pool, _pool([(9, 900, -2.0, 0.0, 0.0)])], ignore_index=True)
    assert list(_rank(pool, floor=0).ranked["player_id"])[:2] == [3, 7]


def test_every_feature_has_a_label():
    assert {f for b in S.BLOCKS for f in b.features} == set(S.FEATURE_LABELS)


def _season() -> str:
    return next(s for s in seasons.seasons() if s in advanced.advanced_seasons())


def _real_pool() -> pd.DataFrame:
    pool = advanced.similarity_pool(_season())
    return S.qualified(pool, minutes_floor(pool))


def test_every_feature_is_a_column_of_the_similarity_pool(con):
    assert set(S.FEATURE_LABELS) <= set(advanced.similarity_pool(_season()).columns)


def test_a_modern_season_uses_every_block(con):
    pool = _real_pool()
    result = S.rank_similar(pool, int(pool["player_id"].iloc[0]), 0)
    assert result.blocks == [b.name for b in S.BLOCKS]


def test_real_matches_share_a_role(con):
    # The season's leading shot-blocker over the floor: his closest matches
    # block shots too, well above the pool's median.
    pool = _real_pool()
    big = pool.sort_values("block_pct", ascending=False).iloc[0]
    top = S.rank_similar(pool, int(big["player_id"]), 0, n=5).ranked
    assert (top["block_pct"] > pool["block_pct"].median()).all()
