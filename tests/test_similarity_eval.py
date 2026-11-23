"""dashboard/lib/similarity_eval.py: the self-match test, on synthetic
pools."""

import numpy as np
import pandas as pd
import pytest

from dashboard.lib import similarity as S
from dashboard.lib import similarity_eval as E

BLOCKS = (S.Block("Style", 1.0, {"a": 1.0, "b": 1.0}),)


def _season(rows: list[tuple[int, float, float]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["player_id", "a", "b"]).assign(minutes=900)


# Five players on a grid, far apart; season two moves each a little.
ONE = _season([(1, 0.0, 0.0), (2, 5.0, 0.0), (3, 0.0, 5.0), (4, 5.0, 5.0), (5, 2.5, 2.5)])
TWO = _season([(1, 0.3, 0.1), (2, 5.2, 0.2), (3, 0.1, 4.8), (4, 4.9, 5.1), (5, 2.4, 2.7)])
MODEL = E.block_model("test", BLOCKS)


def test_a_stable_player_finds_himself_first():
    ranks = E.self_match(ONE, TWO, MODEL)
    assert list(ranks["player_id"]) == [1, 2, 3, 4, 5]
    assert (ranks["rank"] == 1).all()
    s = E.summarize(ranks, len(TWO))
    assert (s.players, s.candidates, s.top1, s.top5, s.median_rank) == (5, 5, 1.0, 1.0, 1.0)


def test_players_who_swap_styles_dont_find_themselves():
    swapped = TWO.assign(player_id=[2, 1, 3, 4, 5])
    ranks = E.self_match(ONE, swapped, MODEL).set_index("player_id")["rank"]
    assert ranks[1] > 1 and ranks[2] > 1
    assert ranks[3] == 1


def test_only_players_in_both_seasons_are_tested_against_everyone():
    second = pd.concat([TWO, _season([(9, 0.2, 0.0)])], ignore_index=True)
    ranks = E.self_match(ONE.iloc[:4], second, MODEL)
    assert list(ranks["player_id"]) == [1, 2, 3, 4]
    # 9 sits right on 1's season-one spot, so 1 drops to second.
    assert ranks.set_index("player_id").loc[1, "rank"] == 2


def test_a_tie_counts_against_him():
    second = pd.concat([TWO, _season([(9, 0.3, 0.1)])], ignore_index=True)
    assert E.self_match(ONE, second, MODEL).set_index("player_id").loc[1, "rank"] == 2


def test_the_legacy_model_is_cosine_on_every_players_stats():
    pool = pd.DataFrame({"player_id": [1, 2, 3], **{f: [1.0, 2.0, 3.0] for f in E.LEGACY_FEATURES}})
    emb = E.LEGACY.embed(pool, None)
    assert emb.features == E.LEGACY_FEATURES
    assert E.LEGACY.metric == "cosine"
    # A stat anyone lacks is left out, as the first version did.
    gappy = pool.assign(usage_pct=[1.0, None, 3.0])
    assert "usage_pct" not in E.LEGACY.embed(gappy, None).features


def test_closeness_is_higher_for_closer_vectors():
    a = np.array([[1.0, 0.0]])
    b = np.array([[1.0, 0.0], [2.0, 0.0], [0.0, 1.0]])
    assert list(E.closeness(a, b, "euclidean")[0]) == pytest.approx([0.0, -1.0, -np.sqrt(2)])
    # Cosine can't tell [1, 0] from [2, 0]: the reason the model moved off it.
    assert list(E.closeness(a, b, "cosine")[0]) == pytest.approx([1.0, 1.0, 0.0])
    with pytest.raises(ValueError):
        E.closeness(a, b, "manhattan")


def test_without_drops_features_and_blocks():
    blocks = E.without(features=["height_inches"], blocks=["Role"])
    assert "Role" not in [b.name for b in blocks]
    assert all("height_inches" not in b.features for b in blocks)
    assert len(blocks) == len(S.BLOCKS) - 1
