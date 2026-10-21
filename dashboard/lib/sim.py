"""Season and playoff simulator for the Arcade team builder.

Turns an eight-man roster into a team net rating, and a net rating into
simulated seasons against a league of real teams (Build and Draft mode).

Pure numpy and stdlib, no Streamlit, so the page code stays thin and every
number the game shows is pinned by tests/test_sim.py. All randomness comes
from the numpy Generator the caller passes in; seed it (see roster_seed)
and the same roster always gets the same projection.

The model is deliberately simple. A game margin is Normal(net difference
plus home edge, GAME_SD), which is the usual NBA approximation, and the
roster's net rating comes from the offline impact model's calibration
(net ~ offset + scale * weighted impact).
"""

from __future__ import annotations

import hashlib
import math

import numpy as np

STARTER_MINUTES = 36
BENCH_MINUTES = 20  # 5 x 36 + 3 x 20 = 240, a real game's player-minutes
ROSTER_SIZE = 8
STARTERS = 5
GAME_SD = 12.7  # points; standard deviation of an NBA game margin
HOME_EDGE = 2.5  # points added to the home side's expected margin
SEASON_GAMES = 82
N_SIMS = 1000
# How much of the usage a roster has beyond a league-average lineup it
# loses: there is only one ball. Heuristic, documented in the Arcade page.
USAGE_PENALTY = 0.5
# A roster's net rating is left alone up to the knee and bends smoothly
# towards the ceiling past it (see soft_cap). The best real teams reached
# about +13, so +10 is already elite and nothing realistic gets squashed.
ABS_NET_KNEE = 10.0
ABS_NET_CAP = 16.0


def rotation_weights() -> np.ndarray:
    """Minutes share of each rotation slot, scaled to sum to five.

    Starters play 36 and bench players 20, which fills a game's 240
    player-minutes. Shares are minutes over that total, times 5 (five
    players on the floor at once), the same convention the impact model's
    team calibration was fit with (ml/player_impact.py: minutes share x 5 x
    impact), which is what makes team_scale and team_offset valid here.
    """
    minutes = [STARTER_MINUTES] * STARTERS + [BENCH_MINUTES] * (ROSTER_SIZE - STARTERS)
    minutes = np.asarray(minutes, dtype=float)
    return minutes / minutes.sum() * 5.0


def team_net_rating(
    impacts,
    usages,
    scale: float,
    offset: float,
    usage_league_total: float = 5.0,
) -> float:
    """Expected net rating (points per 100 vs. an average team) of a roster.

    impacts and usages are in rotation order, starters first. Usage beyond
    what a league-average lineup carries costs a share of the roster's
    positive impact: too many ball-dominant players cannot all use the ball.
    """
    impacts = np.asarray(impacts, dtype=float)
    usages = np.asarray(usages, dtype=float)
    if impacts.shape != (ROSTER_SIZE,) or usages.shape != (ROSTER_SIZE,):
        raise ValueError(f"a roster needs exactly {ROSTER_SIZE} players")
    w = rotation_weights()
    weighted_impact = float(np.dot(w, impacts))
    weighted_usage = float(np.dot(w, usages))
    excess = max(0.0, weighted_usage - usage_league_total)
    positive = impacts[impacts > 0]
    mean_positive = float(positive.mean()) if positive.size else 0.0
    penalty = USAGE_PENALTY * excess * max(0.0, mean_positive)
    return offset + scale * weighted_impact - penalty


def soft_cap(net, knee: float = ABS_NET_KNEE, cap: float = ABS_NET_CAP):
    """Leave a net rating alone up to +-knee, then bend it towards +-cap.

    Past the knee: sign(x) * (knee + room * tanh((|x| - knee) / room)), with
    room = cap - knee. That joins the straight line with slope 1, so the
    curve has no kink, and it never quite reaches the cap.

    Real team net ratings top out around +13 (the 1995-96 Bulls, +13.4).
    The impact calibration is linear, so a fantasy roster of eight star
    seasons extrapolates far past anything real (+38 and up); the ceiling
    keeps such superteams near the best ever, while any rating a real team
    could have, up to +10, is shown exactly as computed (+13.65 comes out
    about +13.3). Works on floats (returns a float) and numpy arrays
    (returns an array).
    """
    x = np.asarray(net, dtype=float)
    size = np.abs(x)
    room = cap - knee
    bent = knee + room * np.tanh((size - knee) / room)
    out = np.sign(x) * np.where(size <= knee, size, bent)
    return float(out) if out.ndim == 0 else out


def _norm_cdf(x):
    """Standard normal CDF. Works on floats and numpy arrays."""
    return 0.5 * (1.0 + _erf(np.asarray(x, dtype=float) / math.sqrt(2.0)))


_erf = np.vectorize(math.erf, otypes=[float])


def win_prob(net_a: float, net_b: float, home_edge: float = 0.0) -> float:
    """Chance A beats B: P(margin > 0), margin ~ Normal(a - b + edge, GAME_SD)."""
    z = (float(net_a) - float(net_b) + home_edge) / GAME_SD
    return float(_norm_cdf(z))


def _vs_league_schedule(n_opps: int, rng: np.random.Generator):
    """Build mode's 82 games: (opponent index per game, is_home per game).

    The opponents are shuffled once (a permutation drawn from rng, so a
    seeded projection is still reproducible) and then cycled through, so
    the leftover games of an uneven split (82 against 30 teams leaves 22
    third meetings) go to a random set of teams rather than the first ones
    alphabetically. The venue alternates within a cycle and flips every
    cycle: with an even league, plain alternation would line each opponent
    up with the same parity every time round, always home or always away.
    Over 82 games the team hosts 41 (for any league of two or more).
    """
    order = rng.permutation(n_opps)
    k = np.arange(SEASON_GAMES)
    slot, cycle = k % n_opps, k // n_opps
    return order[slot], (slot + cycle) % 2 == 0


def simulate_vs_league(
    team_net: float, opponent_nets, rng: np.random.Generator, n_sims: int = N_SIMS
) -> dict:
    """Simulate n_sims 82-game seasons for one team against a league.

    The schedule comes from _vs_league_schedule (drawn from rng first, so
    simulate_season_once with an identically seeded rng plays the same
    one). Each opponent also plays a simplified season of its own,
    Binomial(82, p) against the average opponent, so the team's best-record
    odds can be read off the same sims. A tie with the best other record
    counts as holding it.
    """
    opps = np.asarray(opponent_nets, dtype=float)
    idx, home = _vs_league_schedule(len(opps), rng)
    mean_margin = team_net - opps[idx] + np.where(home, HOME_EDGE, -HOME_EDGE)
    margins = rng.normal(mean_margin, GAME_SD, size=(n_sims, SEASON_GAMES))
    wins = (margins > 0).sum(axis=1)

    p_opp = _norm_cdf((opps - opps.mean()) / GAME_SD)
    opp_wins = rng.binomial(SEASON_GAMES, p_opp, size=(n_sims, len(opps)))
    best_record = float(np.mean(wins >= opp_wins.max(axis=1)))

    return {
        "wins": wins,
        "median": int(round(float(np.median(wins)))),
        "p10": int(round(float(np.percentile(wins, 10)))),
        "p90": int(round(float(np.percentile(wins, 90)))),
        "best_record_odds": best_record,
    }


def simulate_season_once(team_net: float, opponent_nets, rng: np.random.Generator) -> dict:
    """One season, game by game: [(opp_index, is_home, margin, won)].

    Same schedule as simulate_vs_league (_vs_league_schedule). opp_index
    points into the opponent_nets list; margin is from the team's side.
    """
    opps = np.asarray(opponent_nets, dtype=float)
    idx, home = _vs_league_schedule(len(opps), rng)
    mean_margin = team_net - opps[idx] + np.where(home, HOME_EDGE, -HOME_EDGE)
    margins = rng.normal(mean_margin, GAME_SD)
    games = [
        (int(idx[k]), bool(home[k]), float(margins[k]), bool(margins[k] > 0))
        for k in range(SEASON_GAMES)
    ]
    wins = sum(1 for g in games if g[3])
    return {"games": games, "wins": wins, "losses": SEASON_GAMES - wins}


def roster_seed(player_ids) -> int:
    """A stable seed from a set of player ids, whatever their order.

    The same roster always gets the same projection, run after run.
    """
    key = ",".join(map(str, sorted(player_ids)))
    return int(hashlib.sha256(key.encode()).hexdigest()[:8], 16)
