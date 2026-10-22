"""The "How the simulation works" expander under Build a team: plain-language
notes on impact, minutes, usage overlap, game randomness, the rating ceiling
and Draft's hidden budget. Numbers come from the constants it explains.
"""

import streamlit as st

from core.constants import (
    COMPLETE_BOX_SCORE_FIRST_SEASON,
    GAME_MARGIN_SD,
    HOME_EDGE_POINTS,
    MAX_COST,
)
from dashboard.lib import sim
from dashboard.lib.draft import DRAFT_BUDGET_MAX, DRAFT_BUDGET_MIN


def explainer(meta_row: dict) -> None:
    """The expander under the tab; `meta_row` is the impact model's metadata."""
    r2 = meta_row.get("team_r2")
    fit = (
        f" On real team-seasons the conversion explains {float(r2):.0%} of the "
        f"spread in net rating."
        if r2 is not None and r2 == r2
        else ""
    )
    with st.expander("How the simulation works"):
        st.markdown(
            f"""
**Impact.** Every player-season since {COMPLETE_BOX_SCORE_FIRST_SEASON} gets one number:
points, rebounds, assists, steals, blocks, turnovers, shots and fouls per 36
minutes, each weighed by a model fit to how much players' teams outscored
opponents while they were on the court. 0 is a typical rotation player; the best seasons ever reach about +5 to +6.

**Era adjustment.** Every rate is compared with that season's league average
before it's weighed, so a 1988 rebounder and a 2024 shooter are rated on the same
scale. That's what makes an all-time team possible.

**Minutes.** Your top row starts and plays {sim.STARTER_MINUTES} minutes; the
three bench players play {sim.BENCH_MINUTES} (5 × {sim.STARTER_MINUTES} + 3 ×
{sim.BENCH_MINUTES} = 240, one game's worth of player-minutes). Impact weighted by
those minutes becomes the team rating.{fit}

**Usage overlap.** There's only one ball. When a lineup's combined usage (shots,
free throws and turnovers) runs past what a normal lineup carries, part of its
positive impact is lost. This rule is a rough heuristic, not fitted to data.

**Game randomness.** Each game's margin is the rating gap, plus {HOME_EDGE_POINTS}
points for the home team, plus random noise of ±{GAME_MARGIN_SD} points (one standard
deviation, as measured on real NBA games). Good teams lose plenty of single games.

**A ceiling.** Real teams top out around +13 (the 1995-96 Bulls). A rating up to
+{sim.ABS_NET_KNEE:.0f} is shown exactly as computed; past that, a stacked roster's
rating bends smoothly toward a +{sim.ABS_NET_CAP:.0f} ceiling instead of running off
the chart. Projections can shift slightly when the weekly data refresh updates the
current season.

**Draft mode's hidden budget.** Every player-season has a price, 1 to {MAX_COST} credits
by impact (Build mode shows it). A draft secretly gets
{DRAFT_BUDGET_MIN}-{DRAFT_BUDGET_MAX} credits, and each round offers one
pricier, one fair and one cheaper player for that spot, so whatever you pick, the
team ends up about as strong as the budget allows. A bigger budget is the lucky
draft.

**Same team, same projection.** The projection plays 1,000 seasons from a seed tied
to your roster, so the same eight players always get the same numbers. "Simulate a
season" plays one fresh season, so each one comes out differently.

It's a game built on real numbers, not a scouting tool.
"""
        )
