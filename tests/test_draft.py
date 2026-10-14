"""The Arcade team builder's rules and CPU drafting: budget validation,
snake order, the CPU's pick logic, a whole seeded draft, and the db pool
loaders. Pure pandas/numpy plus the tmp-warehouse fixtures in conftest.py."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dashboard.lib import db, draft, sim  # noqa: E402


def _picks(n=8, cost=5, dup=False):
    rows = [
        {"season": "2024-25", "player_id": i, "player": f"P{i}", "cost": cost,
         "impact": 1.0, "usage": 1.0}
        for i in range(n)
    ]
    if dup and n >= 2:
        rows[1]["player_id"] = rows[0]["player_id"]
    return pd.DataFrame(rows, columns=["season", "player_id", "player", "cost", "impact", "usage"])


def _pool(n=100, seed=0):
    r = np.random.default_rng(seed)
    return pd.DataFrame({
        "season": "2024-25",
        "player_id": np.arange(n),
        "player": [f"P{i}" for i in range(n)],
        "impact": r.normal(0, 2, n).round(2),
        "usage": r.uniform(0.6, 1.6, n).round(2),
        "cost": r.integers(1, 11, n),
    })


# --- validate_build ------------------------------------------------------------

def test_constants_come_from_sim():
    assert draft.BUDGET == 40
    assert draft.ROSTER_SIZE == sim.ROSTER_SIZE == 8


def test_validate_build_valid_roster_has_no_problems():
    assert draft.validate_build(_picks(8, cost=5)) == []  # exactly 40


def test_validate_build_wrong_count():
    assert draft.validate_build(_picks(7, cost=1)) == ["Pick 8 players (you have 7)."]


def test_validate_build_over_budget():
    picks = _picks(8, cost=5)
    picks.loc[0, "cost"] = 6  # 41
    assert draft.validate_build(picks) == ["Over budget: 41 of 40 credits."]


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


# --- snake_order ---------------------------------------------------------------

def test_snake_order():
    assert draft.snake_order(3, 2, user_slot=0) == [0, 1, 2, 2, 1, 0]
    assert draft.snake_order(2, 3, user_slot=1) == [0, 1, 1, 0, 0, 1]


def test_snake_order_rejects_a_bad_user_slot():
    with pytest.raises(ValueError):
        draft.snake_order(3, 2, user_slot=3)


# --- cpu_pick ------------------------------------------------------------------

def test_cpu_pick_never_returns_a_taken_or_missing_index():
    pool = _pool(40)
    taken = set(range(0, 40, 3))
    available = pool.drop(index=list(taken))
    roster = pool.loc[[1, 2]]
    for seed in range(200):
        pick = draft.cpu_pick(available, roster, np.random.default_rng(seed))
        assert pick in available.index
        assert pick not in taken


def test_cpu_pick_without_noise_takes_the_best_impact_when_usage_is_fine():
    pool = _pool(30)
    pool["usage"] = 1.0  # exactly league average: no usage penalty anywhere
    best = pool["impact"].idxmax()
    assert draft.cpu_pick(pool, pool.iloc[0:0], np.random.default_rng(1), noise_sd=0) == best


def test_cpu_pick_stub_rng_returning_zero_noise():
    class ZeroRng:
        def normal(self, loc, scale, size=None):
            return np.zeros(size)

    pool = _pool(30)
    pool["usage"] = 1.0
    assert draft.cpu_pick(pool, pool.iloc[0:0], ZeroRng()) == pool["impact"].idxmax()


def test_cpu_pick_penalises_a_ball_hog_on_a_usage_heavy_roster():
    # Two near-equal candidates; one would push the roster far past the
    # league usage budget, so the CPU takes the other.
    roster = pd.DataFrame({"impact": [3.0] * 5, "usage": [1.8] * 5})
    available = pd.DataFrame(
        {"impact": [2.0, 1.8], "usage": [2.4, 0.9]}, index=[10, 11]
    )
    pick = draft.cpu_pick(available, roster, np.random.default_rng(0), noise_sd=0)
    assert pick == 11


def test_cpu_pick_does_not_penalise_when_under_the_usage_budget():
    roster = pd.DataFrame({"impact": [1.0], "usage": [0.5]})
    available = pd.DataFrame({"impact": [2.0, 1.9], "usage": [1.2, 0.8]}, index=[7, 9])
    assert draft.cpu_pick(available, roster, np.random.default_rng(0), noise_sd=0) == 7


def test_cpu_pick_rejects_an_empty_pool_and_a_full_roster():
    pool = _pool(10)
    rng = np.random.default_rng(0)
    with pytest.raises(ValueError):
        draft.cpu_pick(pool.iloc[0:0], pool.iloc[0:0], rng)
    with pytest.raises(ValueError):
        draft.cpu_pick(pool.iloc[8:], pool.iloc[:8], rng)


# --- full draft ----------------------------------------------------------------

def _run_full_draft(seed, user_team=0, n_teams=6, rounds=8, pool=None):
    pool = _pool(100) if pool is None else pool
    rng = np.random.default_rng(seed)
    state = draft.new_draft(n_teams, rounds, user_team)
    draft.run_cpu_until_user(state, pool, rng)
    # The "user" takes the best-impact player left each time.
    while state["pick_no"] < len(state["order"]):
        assert state["order"][state["pick_no"]] == user_team
        left = pool.loc[~pool.index.isin(state["taken"])]
        draft.apply_pick(state, left["impact"].idxmax())
        draft.run_cpu_until_user(state, pool, rng)
    return state


def test_full_draft_fills_every_roster_with_no_repeats():
    state = _run_full_draft(seed=3)
    assert state["pick_no"] == 48
    all_picks = [i for r in state["rosters"].values() for i in r]
    assert all(len(r) == 8 for r in state["rosters"].values())
    assert len(all_picks) == len(set(all_picks)) == 48
    assert state["taken"] == set(all_picks)


def test_full_draft_is_deterministic_for_a_fixed_seed():
    a = _run_full_draft(seed=11)
    b = _run_full_draft(seed=11)
    c = _run_full_draft(seed=12)
    assert a["rosters"] == b["rosters"]
    assert a["rosters"] != c["rosters"]


def test_run_cpu_until_user_stops_on_the_users_turn():
    pool = _pool(100)
    state = draft.new_draft(6, 8, user_team=2)
    draft.run_cpu_until_user(state, pool, np.random.default_rng(0))
    assert state["pick_no"] == 2  # teams 0 and 1 picked
    assert state["order"][state["pick_no"]] == 2
    assert len(state["taken"]) == 2
    # Nothing more happens while it is still the user's turn.
    draft.run_cpu_until_user(state, pool, np.random.default_rng(0))
    assert state["pick_no"] == 2


def test_run_cpu_until_user_honours_an_explicit_user_team():
    pool = _pool(100)
    state = draft.new_draft(6, 8, user_team=0)
    draft.run_cpu_until_user(state, pool, np.random.default_rng(0), user_team=3)
    assert state["pick_no"] == 3


def test_apply_pick_rejects_a_taken_player():
    state = draft.new_draft(3, 2, user_team=0)
    draft.apply_pick(state, 5)
    with pytest.raises(ValueError):
        draft.apply_pick(state, 5)


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
