"""Rules and CPU drafting for the Arcade team builder.

Build mode: pick eight player-seasons under a 36-credit budget
(validate_build). Draft mode: a snake draft against CPU teams
(snake_order, cpu_pick, run_cpu_until_user). Pure pandas and numpy, no
Streamlit; every random choice comes from the numpy Generator the caller
passes in, so a seeded draft is reproducible.

The pool is the player_impact table (db.player_impact_pool): one row per
player-season with impact, usage and a 1..12 credit cost. Rows are
identified by their index label in whatever pool DataFrame the caller holds;
draft state stores those labels, never positions.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .sim import ROSTER_SIZE, USAGE_PENALTY, rotation_weights

# Tuned with ml.player_impact.COST_QUANTILES; see the targets there.
BUDGET = 36


def validate_build(picks: pd.DataFrame) -> list[str]:
    """Human-readable problems with a Build-mode roster; [] means valid.

    `picks` holds pool rows (player_id, season, cost, ...). The same player
    in two different seasons is fine (all-time mode); the same player-season
    twice is not.
    """
    problems: list[str] = []
    if len(picks) != ROSTER_SIZE:
        problems.append(f"Pick {ROSTER_SIZE} players (you have {len(picks)}).")
    spent = int(picks["cost"].sum()) if len(picks) else 0
    if spent > BUDGET:
        problems.append(f"Over budget: {spent} of {BUDGET} credits.")
    if len(picks) and picks.duplicated(subset=["player_id", "season"]).any():
        problems.append("The same player can't appear twice.")
    return problems


def snake_order(n_teams: int, rounds: int, user_slot: int) -> list[int]:
    """Team index for each pick of a snake draft.

    Round 1 runs 0..n-1, round 2 runs back n-1..0, and so on. Team indexes
    are draft positions and the user is team `user_slot`; it is validated
    here but does not change the order.
    """
    if not 0 <= user_slot < n_teams:
        raise ValueError(f"user_slot {user_slot} is not a team in 0..{n_teams - 1}")
    order: list[int] = []
    for r in range(rounds):
        teams = list(range(n_teams))
        order.extend(teams if r % 2 == 0 else reversed(teams))
    return order


def cpu_pick(
    available: pd.DataFrame,
    roster: pd.DataFrame,
    rng,
    usage_league_total: float = 5.0,
    noise_sd: float = 0.3,
):
    """The index label (from `available`) the CPU drafts next.

    Score = impact - USAGE_PENALTY * excess + Normal(0, noise_sd), argmax.

    The usage term mirrors the simulator's one-ball rule using the same
    minutes weights (sim.rotation_weights, summing to 5). The candidate
    takes the next rotation slot, index len(roster); `roster` rows count in
    the order given, one per slot. Projected usage is the minutes-weighted
    sum of the roster's usage plus w_next * candidate usage. A roster of
    league-average players (usage 1.0 each) projects to the sum of the
    weights used, so the allowance is usage_league_total * (sum of those
    weights) / 5. excess = max(0, projected - allowance).

    Never returns an index that is not in `available`.
    """
    if len(available) == 0:
        raise ValueError("no players left to pick from")
    slot = len(roster)
    if slot >= ROSTER_SIZE:
        raise ValueError("this roster is already full")

    w = rotation_weights()
    held = (w[:slot] * roster["usage"].to_numpy(dtype=float)).sum() if slot else 0.0
    projected = held + w[slot] * available["usage"].to_numpy(dtype=float)
    allowance = usage_league_total * w[: slot + 1].sum() / 5.0
    excess = np.maximum(0.0, projected - allowance)

    noise = np.asarray(rng.normal(0.0, noise_sd, size=len(available)), dtype=float)
    score = available["impact"].to_numpy(dtype=float) - USAGE_PENALTY * excess + noise
    return available.index[int(np.argmax(score))]


def new_draft(n_teams: int, rounds: int, user_team: int) -> dict:
    """A fresh draft state.

    {"order": team index per pick, "pick_no": next pick (0-based),
     "rosters": {team_idx: [pool index label, ...]}, "taken": set of labels,
     "user_team": the human's team index}
    """
    return {
        "order": snake_order(n_teams, rounds, user_team),
        "pick_no": 0,
        "rosters": {t: [] for t in range(n_teams)},
        "taken": set(),
        "user_team": user_team,
    }


def apply_pick(state: dict, pool_index) -> None:
    """Record `pool_index` for whoever is on the clock and advance the draft."""
    if state["pick_no"] >= len(state["order"]):
        raise ValueError("the draft is over")
    if pool_index in state["taken"]:
        raise ValueError(f"pool index {pool_index!r} is already taken")
    team = state["order"][state["pick_no"]]
    state["rosters"][team].append(pool_index)
    state["taken"].add(pool_index)
    state["pick_no"] += 1


def run_cpu_until_user(
    state: dict,
    pool: pd.DataFrame,
    rng,
    user_team: int | None = None,
    usage_league_total: float = 5.0,
) -> dict:
    """Make CPU picks until it is the user's turn or the draft is done.

    The user's team comes from `user_team` if given, else state["user_team"].
    Mutates and returns `state`.
    """
    user = state["user_team"] if user_team is None else user_team
    while state["pick_no"] < len(state["order"]):
        team = state["order"][state["pick_no"]]
        if team == user:
            break
        available = pool.loc[~pool.index.isin(state["taken"])]
        roster = pool.loc[state["rosters"][team]]
        pick = cpu_pick(available, roster, rng, usage_league_total=usage_league_total)
        apply_pick(state, pick)
    return state


def auto_rotation(roster_rows: pd.DataFrame) -> pd.DataFrame:
    """The roster sorted by impact, best first; the first five are starters."""
    return roster_rows.sort_values("impact", ascending=False, kind="mergesort")
