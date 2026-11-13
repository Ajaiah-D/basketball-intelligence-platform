"""dashboard/lib/similarity.py: the Similar players ranking, on synthetic
pools (no warehouse), plus one sanity check on the real one."""

import numpy as np
import pandas as pd
import pytest

from dashboard.lib import similarity as S
from dashboard.lib.advanced_metrics import minutes_floor
from dashboard.lib.data import advanced, seasons

FEATURES = ["a", "b", "c"]


def _pool(rows: list[tuple[int, int, float, float, float]]) -> pd.DataFrame:
    """(player_id, minutes, a, b, c) rows."""
    return pd.DataFrame(rows, columns=["player_id", "minutes", *FEATURES])


# Player 1's profile; 2 is a scaled copy (the same shape), 3 is close, 4 is
# the mirror image, 5 is a 10-minute cameo with exactly 1's numbers.
POOL = _pool(
    [
        (1, 900, 10.0, 2.0, 5.0),
        (2, 900, 12.0, 1.0, 5.5),
        (3, 900, 9.0, 3.0, 5.0),
        (4, 900, 2.0, 9.0, 1.0),
        (5, 10, 10.0, 2.0, 5.0),
        (6, 900, 6.0, 5.0, 3.0),
    ]
)


def test_the_closest_profile_ranks_first_and_the_opposite_last():
    result = S.rank_similar(POOL, 1, min_minutes=100, n=10, features=FEATURES)
    ids = list(result.ranked["player_id"])
    assert ids[0] in (2, 3)
    assert ids[-1] == 4
    assert result.ranked["similarity"].is_monotonic_decreasing
    assert result.ranked["similarity"].iloc[-1] < 0  # the mirror image
    assert list(result.ranked["rank"]) == list(range(1, len(ids) + 1))


def test_he_is_not_on_his_own_list():
    result = S.rank_similar(POOL, 1, min_minutes=100, features=FEATURES)
    assert 1 not in set(result.ranked["player_id"])


def test_players_under_the_minutes_floor_are_left_out():
    # 5 has exactly his numbers, but only 10 minutes.
    result = S.rank_similar(POOL, 1, min_minutes=100, features=FEATURES)
    assert 5 not in set(result.ranked["player_id"])
    assert result.pool_size == 5
    # With no floor he is the perfect match.
    loose = S.rank_similar(POOL, 1, min_minutes=0, features=FEATURES)
    assert loose.ranked["player_id"].iloc[0] == 5
    assert loose.ranked["similarity"].iloc[0] == pytest.approx(1.0)


def test_a_player_under_the_floor_has_no_list():
    with pytest.raises(S.NotInPoolError):
        S.rank_similar(POOL, 5, min_minutes=100, features=FEATURES)
    with pytest.raises(S.NotInPoolError):
        S.rank_similar(POOL, 99, min_minutes=0, features=FEATURES)


def test_the_list_is_as_long_as_asked_or_the_pool_allows():
    pool = _pool([(i, 900, float(i), float(i % 3), float(i % 5)) for i in range(1, 41)])
    for n in (5, 10, 25):
        assert len(S.rank_similar(pool, 1, 0, n=n, features=FEATURES).ranked) == n
    assert len(S.rank_similar(POOL, 1, 100, n=25, features=FEATURES).ranked) == 4
    with pytest.raises(ValueError):
        S.rank_similar(POOL, 1, 100, n=0, features=FEATURES)


def test_z_scores_are_capped():
    # One huge outlier in `a`: uncapped it would sit near +4.4 sd.
    pool = _pool([(i, 900, 1.0, float(i), 0.0) for i in range(1, 21)] + [(99, 900, 1000.0, 5, 0)])
    z = S.capped_zscores(pool, FEATURES)
    assert z.max() == pytest.approx(S.Z_CAP)
    assert np.abs(z).max() <= S.Z_CAP
    # A stat with no spread scores 0 for everyone instead of dividing by zero.
    assert (z[:, 2] == 0).all()


def test_the_cap_stops_one_extreme_stat_deciding_a_match():
    # Five stats. 1 and 2 are both far off the scale on `a` (about +11 sd)
    # and opposite on the other four; 3 is average on `a` and matches 1 on
    # those four. Uncapped, the shared outlier makes 2 his match; capped at
    # 3 sd, the four stats they actually share make it 3. The filler sets
    # the scale: average on `a`, every other mix of +/-1 on the rest.
    stats = ["a", "b", "c", "d", "e"]
    filler = [
        (100 + i, 900, 0.0, *(1.0 if (i >> bit) & 1 else -1.0 for bit in range(4)))
        for i in range(64)
        if i % 16 != 15
    ]
    rows = [
        (1, 900, 8.0, 1.0, 1.0, 1.0, 1.0),
        (2, 900, 8.0, -1.0, -1.0, -1.0, -1.0),
        (3, 900, 0.0, 1.0, 1.0, 1.0, 1.0),
        *filler,
    ]
    pool = pd.DataFrame(rows, columns=["player_id", "minutes", *stats])

    def top(cap: float) -> int:
        ranked = S.rank_similar(pool, 1, 0, n=1, features=stats, cap=cap).ranked
        return int(ranked["player_id"].iloc[0])

    assert top(float("inf")) == 2
    assert top(S.Z_CAP) == 3


def test_a_stat_some_players_lack_is_left_out_for_everyone():
    pool = POOL.assign(d=[1.0, 2.0, None, 4.0, 5.0, 6.0])
    result = S.rank_similar(pool, 1, 100, features=[*FEATURES, "d"])
    assert result.features == FEATURES
    # A stat missing only below the floor still counts.
    pool = POOL.assign(d=[1.0, 2.0, 3.0, 4.0, None, 6.0])
    assert S.rank_similar(pool, 1, 100, features=[*FEATURES, "d"]).features == [*FEATURES, "d"]


def test_ties_break_on_player_id():
    pool = _pool([(1, 900, 1.0, 0.0, 0.0), (7, 900, 1.0, 0.0, 0.0), (3, 900, 1.0, 0.0, 0.0)])
    pool = pd.concat([pool, _pool([(9, 900, -2.0, 0.0, 0.0)])], ignore_index=True)
    assert list(S.rank_similar(pool, 1, 0, features=FEATURES).ranked["player_id"])[:2] == [3, 7]


def test_every_feature_is_a_mart_column(con):
    cols = {
        r[0]
        for r in con.execute(
            "select column_name from information_schema.columns "
            "where table_name = 'mart_player_season'"
        ).fetchall()
    }
    assert set(S.FEATURES) <= cols


def test_every_feature_is_there_for_every_qualified_player(con):
    # The ranking leaves out a stat anyone lacks; on real data none should be.
    season = next(s for s in seasons.seasons() if s in advanced.advanced_seasons())
    pool = advanced.player_advanced(season)
    floor = minutes_floor(pool)
    assert S.usable_features(S.qualified(pool, floor), S.FEATURES) == list(S.FEATURES)


def test_real_matches_share_a_role(con):
    # The season's leading shot-blocker over the floor: his closest matches
    # block shots too, well above the pool's median.
    season = next(s for s in seasons.seasons() if s in advanced.advanced_seasons())
    pool = advanced.player_advanced(season)
    floor = minutes_floor(pool)
    qualified = S.qualified(pool, floor)
    big = qualified.sort_values("block_pct", ascending=False).iloc[0]
    top = S.rank_similar(pool, int(big["player_id"]), floor, n=5).ranked
    assert (top["block_pct"] > qualified["block_pct"].median()).all()
