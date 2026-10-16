"""Rules for the Arcade team builder.

Build mode: pick eight player-seasons under a 36-credit budget
(validate_build). Draft mode: eight rounds, one per roster spot, each
offering three players to choose from (new_pick_draft, offer_options). A
hidden budget, drawn from 34-40 credits, steers which players are offered,
so every draft ends up a fair team without the player doing any budget
math; a bigger draw is the lucky draft. Pure pandas and numpy, no
Streamlit; every random choice comes from the numpy Generator the caller
passes in, so a seeded draft is reproducible.

The pool is the player_impact table (db.player_impact_pool): one row per
player-season with impact, usage and a 1..12 credit cost. Picks are kept
as (player_id, season) pairs, which survive a data refresh; offer_options
returns index labels of the pool DataFrame it is given.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .sim import ROSTER_SIZE, rotation_weights

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


# Draft mode. The hidden budget is drawn from this range (inclusive).
DRAFT_BUDGET_MIN = 34
DRAFT_BUDGET_MAX = 40
OPTIONS = 3
OPTION_SPREAD = 3  # credits between the pricier, middle and cheaper option
LUCKY_CHANCE = 0.15  # chance a round's top option is a bigger star than usual
LUCKY_BONUS = 3  # extra credits on that lucky top option
MAX_COST = 12


def new_pick_draft(rng) -> dict:
    """A fresh Draft-mode state: {"budget": hidden credits, "picks": [],
    "offer": []}. picks and offer hold (player_id, season) pairs; the picks
    fill the spots in order, starters 1-5 then bench 1-3."""
    budget = int(rng.integers(DRAFT_BUDGET_MIN, DRAFT_BUDGET_MAX + 1))
    return {"budget": budget, "picks": [], "offer": []}


def spot_target(budget_left: float, spot: int) -> float:
    """The fair cost for `spot`: what is left, shared out over the remaining
    spots by their minutes, so a starter spot gets about 1.8x a bench one."""
    w = rotation_weights()
    return float(budget_left * w[spot] / w[spot:].sum())


def offer_options(pool: pd.DataFrame, picks, budget_left: int, spot: int,
                  rng) -> list:
    """Index labels of up to OPTIONS players to choose from for `spot`.

    Their costs sit around spot_target: one pricier, one about fair, one
    cheaper (OPTION_SPREAD apart), and now and then (LUCKY_CHANCE) the
    pricier one is LUCKY_BONUS credits richer still. On the last spot the
    target is everything left. No option ever costs more than the budget
    can carry while leaving a credit for each spot still to fill, so the
    draft never runs dry. Each option is drawn at random among the players
    whose cost is nearest its target; the three are three different players,
    and none is a player-season already picked. Another season of a picked
    player can still be offered.
    """
    rounds_left = ROSTER_SIZE - spot
    if rounds_left < 1:
        raise ValueError("every spot is already filled")
    ceiling = max(1, min(MAX_COST, budget_left - (rounds_left - 1)))
    target = budget_left if rounds_left == 1 else spot_target(budget_left, spot)
    top = target + OPTION_SPREAD
    if rng.random() < LUCKY_CHANCE:
        top += LUCKY_BONUS
    targets = [top, target, target - OPTION_SPREAD]
    targets = [min(max(1, round(t)), ceiling) for t in targets]

    taken = {(int(p), str(s)) for p, s in picks}
    keys = list(zip(pool["player_id"].astype(int), pool["season"].astype(str)))
    avail = pool[[k not in taken for k in keys]]
    labels: list = []
    for t in targets:
        cand = avail[~avail["player_id"].isin(avail.loc[labels, "player_id"])]
        affordable = cand[cand["cost"] <= ceiling]
        cand = affordable if len(affordable) else cand
        if not len(cand):
            break
        gap = (cand["cost"] - t).abs()
        near = cand[gap == gap.min()]
        labels.append(near.index[int(rng.integers(len(near)))])
    return labels


def auto_rotation(roster_rows: pd.DataFrame) -> pd.DataFrame:
    """The roster sorted by impact, best first; the first five are starters."""
    return roster_rows.sort_values("impact", ascending=False, kind="mergesort")
