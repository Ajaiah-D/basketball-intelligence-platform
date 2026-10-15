"""Season and playoff simulator for the Arcade team builder.

Turns an eight-man roster into a team net rating, and a net rating into
simulated seasons: one team against a league (Build mode) or a small
league with a round robin and playoffs (Draft mode).

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

PLAYOFF_TEAMS = 4
SERIES_GAMES = 7
# Games 1, 2, 5 and 7 are hosted by the higher seed (the 2-2-1-1-1 format).
_HIGH_SEED_HOSTS = np.array([True, True, False, False, True, False, True])


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


def simulate_season_once(
    team_net: float, opponent_nets, rng: np.random.Generator
) -> dict:
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


# --- Draft mode: a small league with a round robin and playoffs ----------


def _check_league_size(n: int) -> None:
    if n < 2 or n % 2:
        raise ValueError(
            f"a league needs an even number of teams so every team can play "
            f"82 games (at least 2), got {n}"
        )


def _matchings(n: int) -> list[list[tuple[int, int]]]:
    """The n-1 perfect matchings of a round robin (circle method).

    Together they pair every team with every other exactly once.
    """
    arr = list(range(n))
    rounds = []
    for _ in range(n - 1):
        rounds.append([(arr[k], arr[n - 1 - k]) for k in range(n // 2)])
        arr = [arr[0], arr[-1]] + arr[1:-1]
    return rounds


def _schedule(n: int) -> dict[tuple[int, int], tuple[int, int]]:
    """{(i, j): (games i hosts, games j hosts)} for i < j, 82 per team.

    Every pair meets 82 // (n-1) times. The leftover games per team are
    handed out one whole matching at a time, so each team gets exactly one
    extra game per matching and every team still totals 82. Odd game counts
    give the extra home date to alternating sides.
    """
    _check_league_size(n)
    base, extra = divmod(SEASON_GAMES, n - 1)
    games = {(i, j): base for i in range(n) for j in range(i + 1, n)}
    for matching in _matchings(n)[:extra]:
        for a, b in matching:
            games[(min(a, b), max(a, b))] += 1
    schedule = {}
    for (i, j), g in games.items():
        half = g // 2
        hi, hj = half, half
        if g % 2:
            if (i + j) % 2 == 0:
                hi += 1
            else:
                hj += 1
        schedule[(i, j)] = (hi, hj)
    return schedule


def _regular_season(nets: np.ndarray, rng: np.random.Generator, n_sims: int):
    """Wins per team for n_sims regular seasons: array (n_sims, N)."""
    n = len(nets)
    wins = np.zeros((n_sims, n), dtype=int)
    for (i, j), (hi, hj) in _schedule(n).items():
        # i hosts hi games; j hosts hj games. Each game is an independent
        # Bernoulli, so a pair's wins are Binomial.
        i_home = rng.binomial(hi, win_prob(nets[i], nets[j], HOME_EDGE), size=n_sims)
        j_home = rng.binomial(hj, win_prob(nets[j], nets[i], HOME_EDGE), size=n_sims)
        wins[:, i] += i_home + (hj - j_home)
        wins[:, j] += j_home + (hi - i_home)
    return wins


def _seed_order(wins: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Team indices best-first for each row; ties broken at random."""
    noise = rng.random(wins.shape)  # < 1, so it only separates equal wins
    return np.argsort(-(wins + noise), axis=1)


def _play_series(net_high, net_low, rng: np.random.Generator):
    """Best-of-7 between arrays of nets: (high_wins, low_wins) per series.

    Games are played one by one; counts stop at the clinching game. The
    higher seed hosts games 1, 2, 5 and 7. Playing all seven and reading
    the count at the first 4 gives the same distribution as stopping early.
    """
    net_high = np.atleast_1d(np.asarray(net_high, dtype=float))
    net_low = np.atleast_1d(np.asarray(net_low, dtype=float))
    edge = np.where(_HIGH_SEED_HOSTS, HOME_EDGE, -HOME_EDGE)
    mean = (net_high - net_low)[:, None] + edge[None, :]
    high_took = rng.normal(mean, GAME_SD) > 0
    cum_high = np.cumsum(high_took, axis=1)
    cum_low = np.cumsum(~high_took, axis=1)
    decided = (cum_high == 4) | (cum_low == 4)
    last = decided.argmax(axis=1)
    rows = np.arange(len(net_high))
    return cum_high[rows, last], cum_low[rows, last]


def _playoffs(nets: np.ndarray, order: np.ndarray, rng: np.random.Generator):
    """Run the 4-team bracket for each row of seed order (n_sims, >=4).

    Returns the two semifinals' and the final's results as dicts of arrays.
    """
    seeds = order[:, :PLAYOFF_TEAMS]
    net = nets[seeds]
    semis = []
    winners = []
    ranks = []
    for hi, lo in ((0, 3), (1, 2)):
        hw, lw = _play_series(net[:, hi], net[:, lo], rng)
        high_won = hw > lw
        winners.append(np.where(high_won, seeds[:, hi], seeds[:, lo]))
        ranks.append(np.where(high_won, hi, lo))
        semis.append(
            {"high": seeds[:, hi], "low": seeds[:, lo], "high_wins": hw,
             "low_wins": lw, "winner": winners[-1]}
        )
    # The better regular-season seed of the two finalists hosts the final.
    first_is_high = ranks[0] < ranks[1]
    f_high = np.where(first_is_high, winners[0], winners[1])
    f_low = np.where(first_is_high, winners[1], winners[0])
    hw, lw = _play_series(nets[f_high], nets[f_low], rng)
    final = {
        "high": f_high, "low": f_low, "high_wins": hw, "low_wins": lw,
        "winner": np.where(hw > lw, f_high, f_low),
    }
    return semis, final


def simulate_league(
    team_nets: list[float], rng: np.random.Generator, n_sims: int = N_SIMS
) -> dict:
    """Simulate n_sims Draft-mode seasons for a league of N (even) teams.

    Round robin of 82 games per team, then the top four by wins (ties split
    at random) play 1v4 and 2v3 best-of-7 series and a final.
    """
    nets = np.asarray(team_nets, dtype=float)
    _check_league_size(len(nets))
    if len(nets) < PLAYOFF_TEAMS:
        raise ValueError(
            f"a league needs at least {PLAYOFF_TEAMS} teams for playoffs, got {len(nets)}"
        )
    n = len(nets)
    wins = _regular_season(nets, rng, n_sims)
    order = _seed_order(wins, rng)
    _, final = _playoffs(nets, order, rng)

    playoff_odds = np.zeros(n)
    for t in range(n):
        playoff_odds[t] = np.mean((order[:, :PLAYOFF_TEAMS] == t).any(axis=1))
    title_odds = np.bincount(final["winner"], minlength=n) / n_sims
    return {
        "wins": wins,
        "median_wins": np.median(wins, axis=0),
        "title_odds": title_odds,
        "playoff_odds": playoff_odds,
    }


def simulate_league_once(team_nets: list[float], rng: np.random.Generator) -> dict:
    """One Draft-mode season: standings, playoff bracket and champion.

    Returns {"wins": [per team], "games": [per team], "bracket": [series
    dicts {round, high, low, high_wins, low_wins, winner}], "champion"}.
    """
    nets = np.asarray(team_nets, dtype=float)
    _check_league_size(len(nets))
    if len(nets) < PLAYOFF_TEAMS:
        raise ValueError(
            f"a league needs at least {PLAYOFF_TEAMS} teams for playoffs, got {len(nets)}"
        )
    wins = _regular_season(nets, rng, 1)
    order = _seed_order(wins, rng)
    semis, final = _playoffs(nets, order, rng)

    def series(round_name: str, s: dict) -> dict:
        return {
            "round": round_name,
            "high": int(s["high"][0]),
            "low": int(s["low"][0]),
            "high_wins": int(s["high_wins"][0]),
            "low_wins": int(s["low_wins"][0]),
            "winner": int(s["winner"][0]),
        }

    bracket = [series("semifinal", s) for s in semis] + [series("final", final)]
    return {
        "wins": [int(w) for w in wins[0]],
        "games": [SEASON_GAMES] * len(nets),
        "seeds": [int(t) for t in order[0, :PLAYOFF_TEAMS]],
        "bracket": bracket,
        "champion": bracket[-1]["winner"],
    }


def roster_seed(player_ids) -> int:
    """A stable seed from a set of player ids, whatever their order.

    The same roster always gets the same projection, run after run.
    """
    key = ",".join(map(str, sorted(player_ids)))
    return int(hashlib.sha256(key.encode()).hexdigest()[:8], 16)
