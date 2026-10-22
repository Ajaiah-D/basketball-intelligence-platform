"""The Arcade team builder's rules: Build-mode budget validation, Draft
mode's offers (pick one of three per spot under a hidden budget), and the
db pool loaders. Pure pandas/numpy plus the tmp-warehouse fixtures in
conftest.py."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dashboard.lib import db, draft, sim


def _picks(n=8, cost=5, dup=False):
    rows = [
        {
            "season": "2024-25",
            "player_id": i,
            "player": f"P{i}",
            "cost": cost,
            "impact": 1.0,
            "usage": 1.0,
        }
        for i in range(n)
    ]
    if dup and n >= 2:
        rows[1]["player_id"] = rows[0]["player_id"]
    return pd.DataFrame(rows, columns=["season", "player_id", "player", "cost", "impact", "usage"])


def _pool(n=100, seed=0):
    r = np.random.default_rng(seed)
    return pd.DataFrame(
        {
            "season": "2024-25",
            "player_id": np.arange(n),
            "player": [f"P{i}" for i in range(n)],
            "impact": r.normal(0, 2, n).round(2),
            "usage": r.uniform(0.6, 1.6, n).round(2),
            "cost": r.integers(1, 11, n),
        }
    )


# --- validate_build ------------------------------------------------------------


def test_constants_come_from_sim():
    assert draft.BUDGET == 36
    assert draft.ROSTER_SIZE == sim.ROSTER_SIZE == 8


def test_validate_build_valid_roster_has_no_problems():
    picks = _picks(8, cost=5)
    picks.loc[:3, "cost"] = 4  # 4 x 4 + 4 x 5 = 36, exactly the budget
    assert draft.validate_build(picks) == []


def test_validate_build_wrong_count():
    assert draft.validate_build(_picks(7, cost=1)) == ["Pick 8 players (you have 7)."]


def test_validate_build_over_budget():
    picks = _picks(8, cost=5)
    picks.loc[:2, "cost"] = 4  # 3 x 4 + 5 x 5 = 37
    assert draft.validate_build(picks) == ["Over budget: 37 of 36 credits."]


def test_validate_build_duplicate_player_season():
    assert draft.validate_build(_picks(8, cost=1, dup=True)) == [
        "The same player can't appear twice."
    ]


def test_validate_build_same_player_in_two_seasons_is_fine():
    picks = _picks(8, cost=1)
    picks.loc[1, "player_id"] = picks.loc[0, "player_id"]
    picks.loc[1, "season"] = "2023-24"
    assert draft.validate_build(picks) == []


def test_validate_build_reports_every_problem():
    picks = _picks(7, cost=6, dup=True)
    msgs = draft.validate_build(picks)
    assert len(msgs) == 3
    assert msgs[0].startswith("Pick 8 players")


def test_validate_build_empty():
    assert draft.validate_build(_picks(0)) == ["Pick 8 players (you have 0)."]


# --- Draft mode: pick one of three ------------------------------------------


def _priced_pool(per_cost=6, seasons=("2024-25",)):
    """per_cost players at every cost 1..12, impact rising with cost; with
    two seasons, every player appears in both."""
    rows = []
    for season in seasons:
        pid = 0
        for cost in range(1, 13):
            for k in range(per_cost):
                rows.append(
                    {
                        "season": season,
                        "player_id": pid,
                        "player": f"P{pid}",
                        "cost": cost,
                        "impact": cost * 0.5 + k * 0.01,
                        "usage": 1.0,
                    }
                )
                pid += 1
    return pd.DataFrame(rows)


def _play(pool, rng, choose):
    """Run a whole draft; `choose` picks one of the offered labels."""
    state = draft.new_pick_draft(rng)
    spent = 0
    for spot in range(sim.ROSTER_SIZE):
        offer = draft.offer_options(pool, state["picks"], state["budget"] - spent, spot, rng)
        label = choose(pool.loc[offer])
        r = pool.loc[label]
        state["picks"].append((int(r.player_id), str(r.season)))
        spent += int(r.cost)
    return state, spent


def test_new_pick_draft_budget_is_drawn_from_the_range():
    budgets = {draft.new_pick_draft(np.random.default_rng(s))["budget"] for s in range(300)}
    assert budgets == set(range(draft.DRAFT_BUDGET_MIN, draft.DRAFT_BUDGET_MAX + 1))


def test_spot_target_shares_the_budget_by_minutes():
    # Fresh 36-credit budget: a starter spot is 36/240 of it, a bench spot 20/240.
    assert draft.spot_target(36, 0) == pytest.approx(36 * 36 / 240)
    assert draft.spot_target(36, 7) == pytest.approx(36)  # the last spot gets the rest
    # With only the three bench spots left, each gets a third.
    assert draft.spot_target(30, 5) == pytest.approx(10)


def test_offer_is_three_different_players_around_the_target():
    pool = _priced_pool()
    for seed in range(50):
        offer = draft.offer_options(pool, [], 37, 0, np.random.default_rng(seed))
        rows = pool.loc[offer]
        assert len(rows) == draft.OPTIONS
        assert rows["player_id"].is_unique
        costs = sorted(rows["cost"], reverse=True)
        # target 37 * 36/240 = 5.55: middle option 6, cheaper 3 (lucky or not).
        assert costs[1:] == [6, 3]
        assert costs[0] in (9, 12)


def test_offer_never_repeats_a_picked_player_season_but_may_offer_another_season():
    pool = _priced_pool(per_cost=1, seasons=("2023-24", "2024-25"))
    # Every 2024-25 player at cost 6 is taken: the middle option must be the
    # 2023-24 season of that same player.
    six = pool[(pool["cost"] == 6) & (pool["season"] == "2024-25")]
    picks = [(int(six.iloc[0].player_id), "2024-25")]
    seen_other_season = False
    for seed in range(40):
        offer = draft.offer_options(pool, picks, 37, 0, np.random.default_rng(seed))
        keys = {(int(r.player_id), r.season) for r in pool.loc[offer].itertuples()}
        assert picks[0] not in keys
        seen_other_season |= (picks[0][0], "2023-24") in keys
    assert seen_other_season


def test_offers_never_cost_more_than_the_budget_can_carry():
    pool = _priced_pool()
    # 9 credits left with 4 spots to fill: nothing above 9 - 3 = 6.
    for seed in range(50):
        offer = draft.offer_options(pool, [], 9, 4, np.random.default_rng(seed))
        assert pool.loc[offer, "cost"].max() <= 6


def test_any_way_through_a_draft_stays_within_the_hidden_budget():
    pool = _priced_pool()

    def pricey(rows):
        return rows["cost"].idxmax()

    def cheap(rows):
        return rows["cost"].idxmin()

    for seed in range(30):
        for choose in (pricey, cheap):
            state, spent = _play(pool, np.random.default_rng(seed), choose)
            assert len(state["picks"]) == sim.ROSTER_SIZE
            assert spent <= state["budget"]
    # Always taking the best option spends nearly all of it.
    state, spent = _play(pool, np.random.default_rng(3), pricey)
    assert spent >= state["budget"] - 3


def test_taking_the_cheap_option_leaves_better_options_later():
    pool = _priced_pool()
    rng = np.random.default_rng(1)
    rich = draft.offer_options(pool, [], 36, 5, rng)
    poor = draft.offer_options(pool, [], 12, 5, rng)
    assert pool.loc[rich, "cost"].min() > pool.loc[poor, "cost"].min()


def test_offer_options_rejects_a_full_roster():
    with pytest.raises(ValueError, match="every spot is already filled"):
        draft.offer_options(_priced_pool(), [], 10, sim.ROSTER_SIZE, np.random.default_rng(0))


# --- auto_rotation -------------------------------------------------------------


def test_auto_rotation_sorts_by_impact_desc():
    rows = pd.DataFrame({"player": list("abcdefgh"), "impact": [1, 5, 3, 8, 2, 7, 4, 6]})
    out = draft.auto_rotation(rows)
    assert out["impact"].tolist() == [8, 7, 6, 5, 4, 3, 2, 1]
    assert out["player"].iloc[0] == "d"


# --- db pool loaders -----------------------------------------------------------


def test_player_impact_unavailable_on_a_warehouse_without_the_tables(tmp_warehouse_without_marts):
    assert db.player_impact_available() is False


def test_player_impact_available_with_the_tables(warehouse_with_player_impact):
    assert db.player_impact_available() is True


def test_player_impact_pool_one_season(warehouse_with_player_impact):
    pool = db.player_impact_pool("2024-25")
    assert len(pool) == 10
    assert set(pool["season"]) == {"2024-25"}
    assert pool["impact"].is_monotonic_decreasing
    assert {"player_id", "player", "team", "impact", "usage", "cost"} <= set(pool.columns)


def test_player_impact_pool_every_season(warehouse_with_player_impact):
    pool = db.player_impact_pool(None)
    assert len(pool) == 20
    assert set(pool["season"]) == {"2023-24", "2024-25"}
    assert pool["impact"].is_monotonic_decreasing


def test_player_impact_meta_is_one_row_dict(warehouse_with_player_impact):
    meta = db.player_impact_meta()
    assert meta["usage_league_total"] == 5.0
    assert meta["team_scale"] == pytest.approx(1.9)
