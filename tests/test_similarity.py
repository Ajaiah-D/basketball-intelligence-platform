"""dashboard/lib/similarity.py: the Similar players ranking, on synthetic
pools (no warehouse), plus sanity checks on the real one."""

import duckdb
import numpy as np
import pandas as pd
import pytest

from dashboard.lib import similarity as S
from dashboard.lib.advanced_metrics import minutes_floor
from dashboard.lib.data import advanced, core, seasons

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


def test_a_block_name_with_a_space_makes_a_plain_column_name():
    assert S.block_column("Shot diet") == "shot_diet_match"
    assert S.block_column("Role") == "role_match"


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


def test_scoring_is_split_into_shot_diet_and_play_type():
    # How he scores, by where he shoots from and how he gets the shot; role
    # still weighs least.
    names = [b.name for b in S.BLOCKS]
    assert names[:2] == ["Shot diet", "Play type"]
    assert set(S.PLAY_TYPE_FEATURES) == set(S.BLOCKS[1].features)
    assert "restricted_area_share" in S.BLOCKS[0].features
    role = next(b for b in S.BLOCKS if b.name == "Role")
    assert all(role.weight <= b.weight for b in S.BLOCKS)


def _play_pool() -> pd.DataFrame:
    """Four players: shares of one play type and their possessions."""
    return pd.DataFrame(
        {
            "player_id": [1, 2, 3, 4],
            "post_up_share": [0.5, 0.5, 0.1, None],
            "play_type_possessions": [20.0, 2000.0, 1000.0, None],
        }
    )


def test_a_small_play_type_sample_is_pulled_toward_the_pool_average():
    pool = _play_pool()
    out = S.shrink_play_types(pool, prior=100.0)
    mean = pool["post_up_share"].mean()
    small, big = out["post_up_share"].iloc[0], out["post_up_share"].iloc[1]
    # (share * n + prior * mean) / (n + prior)
    assert small == pytest.approx((0.5 * 20 + 100 * mean) / 120)
    assert big == pytest.approx((0.5 * 2000 + 100 * mean) / 2100)
    assert mean < small < big < 0.5
    # A player without play types stays without; the input is not changed.
    assert pd.isna(out["post_up_share"].iloc[3])
    assert pool["post_up_share"].iloc[0] == 0.5


def test_no_shrinking_without_a_prior_or_possessions():
    pool = _play_pool()
    pd.testing.assert_frame_equal(S.shrink_play_types(pool, prior=0.0), pool)
    no_counts = pool.drop(columns="play_type_possessions")
    pd.testing.assert_frame_equal(S.shrink_play_types(no_counts, prior=100.0), no_counts)


def test_a_season_without_play_types_ranks_without_that_block():
    # Before 2015-16 (or on a warehouse published before the play types):
    # the Play type block is left out for everyone, the rest still ranks.
    rng = np.random.default_rng(0)
    features = {f for b in S.BLOCKS for f in b.features}
    pool = pd.DataFrame(rng.normal(size=(30, len(features))), columns=sorted(features))
    pool = pool.assign(player_id=range(1, 31), minutes=900.0)
    for f in S.PLAY_TYPE_FEATURES:
        pool[f] = None
    result = S.rank_similar(pool, 1, 0)
    assert "Play type" not in result.blocks
    assert result.blocks == [b.name for b in S.BLOCKS if b.name != "Play type"]


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


def test_a_warehouse_without_screen_assists_gets_them_as_nulls(tmp_path):
    # A warehouse published before the column existed: the pool still
    # loads, and the model leaves the feature out.
    path = tmp_path / "old.duckdb"
    with duckdb.connect(str(path)) as con:
        con.execute("create schema main_marts")
        con.execute(
            "create table main_marts.mart_player_season as select '2024-25' as season, "
            "1 as player_id, 900.0 as minutes, 90.0 as tpa_total"
        )
        con.execute(
            "create table main_marts.mart_player_defense as select '2024-25' as season, "
            "1 as player_id, 2.0 as fouls_per_36, 10.0 as rim_fga, 40.0 as d_fga, "
            "5.0 as contested_per_36, 2.0 as deflections_per_36"
        )
    with core.use_warehouse(path):
        core.clear_caches()
        pool = advanced.similarity_pool("2024-25")
    core.clear_caches()
    assert pool["screen_assists_per_36"].isna().all()
    assert pool["rim_share"].tolist() == [0.25]


def _old_warehouse(path, scoring: bool) -> None:
    """A warehouse with the season mart, and the scoring mart only if asked."""
    with duckdb.connect(str(path)) as con:
        con.execute("create schema main_marts")
        con.execute(
            "create table main_marts.mart_player_season as select '2024-25' as season, "
            "1 as player_id, 900.0 as minutes, 90.0 as tpa_total"
        )
        if scoring:
            con.execute(
                "create table main_marts.mart_player_scoring as select '2024-25' as season, "
                "1 as player_id, 0.4 as restricted_area_share, 0.3 as post_up_share"
            )


def test_a_warehouse_without_the_scoring_mart_gets_the_shot_diet_as_nulls(tmp_path):
    path = tmp_path / "old.duckdb"
    _old_warehouse(path, scoring=False)
    with core.use_warehouse(path):
        core.clear_caches()
        pool = advanced.similarity_pool("2024-25")
    core.clear_caches()
    assert len(pool) == 1
    for column in advanced.SCORING_COLUMNS:
        assert pool[column].isna().all(), column


def test_the_scoring_mart_adds_the_shot_diet_and_play_types(tmp_path):
    # A column the mart lacks (an older mart_player_scoring) comes as null.
    path = tmp_path / "new.duckdb"
    _old_warehouse(path, scoring=True)
    with core.use_warehouse(path):
        core.clear_caches()
        pool = advanced.similarity_pool("2024-25")
    core.clear_caches()
    assert pool["restricted_area_share"].tolist() == [0.4]
    assert pool["post_up_share"].tolist() == [0.3]
    assert pool["isolation_share"].isna().all()


def test_the_real_pool_has_a_shot_diet_and_play_types(con):
    pool = _real_pool()
    zones = pool[
        [
            "restricted_area_share",
            "paint_share",
            "mid_range_share",
            "corner_three_share",
            "above_break_three_share",
        ]
    ]
    assert zones.notna().mean().min() >= S.MIN_COVERAGE
    assert ((zones.dropna().sum(axis=1) - 1).abs() < 1e-6).all()
    assert pool["post_up_share"].notna().mean() >= S.MIN_COVERAGE
