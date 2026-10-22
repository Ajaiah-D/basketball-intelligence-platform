"""The Arcade simulator: rosters to net ratings, net ratings to seasons.

Everything random is driven by a seeded numpy Generator, so these tests
pin both the statistics (a net-0 team wins about 41 of 82 against a league
of net-0 teams) and the bookkeeping (every team plays exactly 82 games).
"""

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.constants import HOME_EDGE_POINTS
from dashboard.lib import sim


def test_rotation_weights_sum_to_five():
    w = sim.rotation_weights()
    assert len(w) == sim.ROSTER_SIZE
    assert w.sum() == pytest.approx(5.0)
    assert w[0] == pytest.approx(5 * 36 / 240)
    assert w[-1] == pytest.approx(5 * 20 / 240)


def test_rotation_minutes_fill_a_240_minute_game():
    bench = sim.ROSTER_SIZE - sim.STARTERS
    assert sim.STARTERS * sim.STARTER_MINUTES + bench * sim.BENCH_MINUTES == 240


def test_team_net_rating_is_offset_plus_scaled_weighted_impact():
    impacts = [1.0] * 8
    usages = [1.0] * 8
    # Weighted impact is 5.0 and weighted usage exactly the league total.
    assert sim.team_net_rating(impacts, usages, 2.0, -1.0) == pytest.approx(9.0)


def test_usage_penalty_lowers_net_for_ball_dominant_rosters():
    impacts = [3.0, 2.5, 2.0, 1.5, 1.0, 0.5, 0.0, -1.0]
    average = [1.0] * 8
    hogs = [1.5] * 8
    base = sim.team_net_rating(impacts, average, 2.0, -1.0)
    crowded = sim.team_net_rating(impacts, hogs, 2.0, -1.0)
    assert crowded < base
    # U = 7.5, excess 2.5, mean positive impact = 1.75
    assert base - crowded == pytest.approx(0.5 * 2.5 * 1.75)


def test_usage_penalty_is_zero_without_positive_impacts_or_excess():
    negative = [-1.0] * 8
    assert sim.team_net_rating(negative, [2.0] * 8, 2.0, 0.0) == pytest.approx(2.0 * -5.0)
    positive = [1.0] * 8
    assert sim.team_net_rating(positive, [0.5] * 8, 2.0, 0.0) == pytest.approx(10.0)


def test_team_net_rating_rejects_wrong_roster_size():
    with pytest.raises(ValueError, match="a roster needs exactly 8 players"):
        sim.team_net_rating([1.0] * 7, [1.0] * 7, 2.0, 0.0)


def test_win_prob_basics():
    assert sim.win_prob(0, 0) == pytest.approx(0.5)
    assert sim.win_prob(5, 0) > 0.6
    assert sim.win_prob(0, 5) < 0.4
    assert sim.win_prob(0, 0, home_edge=HOME_EDGE_POINTS) > 0.5
    assert sim.win_prob(3, 1) + sim.win_prob(1, 3) == pytest.approx(1.0)


def test_simulate_vs_league_is_deterministic_for_a_seed():
    league = [0.0] * 29
    a = sim.simulate_vs_league(4.0, league, np.random.default_rng(7), n_sims=200)
    b = sim.simulate_vs_league(4.0, league, np.random.default_rng(7), n_sims=200)
    assert np.array_equal(a["wins"], b["wins"])
    assert a["median"] == b["median"]
    assert a["best_record_odds"] == b["best_record_odds"]


def test_simulate_vs_league_output_shape():
    out = sim.simulate_vs_league(0.0, [0.0] * 29, np.random.default_rng(1), n_sims=300)
    assert out["wins"].shape == (300,)
    assert out["wins"].min() >= 0 and out["wins"].max() <= sim.SEASON_GAMES
    assert out["p10"] <= out["median"] <= out["p90"]
    assert 0.0 <= out["best_record_odds"] <= 1.0
    assert isinstance(out["median"], int)


def test_simulate_vs_league_accepts_a_league_of_thirty():
    out = sim.simulate_vs_league(2.0, [0.0] * 30, np.random.default_rng(1), n_sims=50)
    assert out["wins"].shape == (50,)


def test_higher_net_means_more_median_wins():
    league = [0.0] * 29
    strong = sim.simulate_vs_league(8.0, league, np.random.default_rng(3))
    average = sim.simulate_vs_league(0.0, league, np.random.default_rng(3))
    assert strong["median"] > average["median"]
    assert strong["best_record_odds"] > average["best_record_odds"]


def test_average_team_wins_about_forty_one():
    out = sim.simulate_vs_league(0.0, [0.0] * 29, np.random.default_rng(11), n_sims=2000)
    assert out["wins"].mean() == pytest.approx(41, abs=1.5)


def test_plus_five_team_wins_over_fifty():
    out = sim.simulate_vs_league(5.0, [0.0] * 29, np.random.default_rng(11), n_sims=2000)
    assert out["wins"].mean() > 50


def test_best_record_odds_are_tiny_for_average_and_large_for_dominant():
    league = [0.0] * 29
    avg = sim.simulate_vs_league(0.0, league, np.random.default_rng(5))
    great = sim.simulate_vs_league(15.0, league, np.random.default_rng(5))
    assert avg["best_record_odds"] < 0.05
    assert great["best_record_odds"] > 0.9


def test_simulate_season_once_records_every_game():
    season = sim.simulate_season_once(3.0, [0.0] * 29, np.random.default_rng(2))
    games = season["games"]
    assert len(games) == sim.SEASON_GAMES
    assert season["wins"] + season["losses"] == sim.SEASON_GAMES
    assert season["wins"] == sum(1 for g in games if g[3])
    assert sum(1 for g in games if g[1]) == sim.SEASON_GAMES // 2
    opp, is_home, margin, won = games[0]
    assert 0 <= opp < 29 and is_home is True and won == (margin > 0)


@pytest.mark.parametrize("n_opps", [29, 30])
def test_vs_league_schedule_balances_venues_per_opponent(n_opps):
    for seed in range(5):
        games = sim.simulate_season_once(0.0, [0.0] * n_opps, np.random.default_rng(seed))["games"]
        venues = {}
        for opp, is_home, _, _ in games:
            venues.setdefault(opp, []).append(is_home)
        assert set(venues) == set(range(n_opps))
        assert all(len(v) in (2, 3) for v in venues.values())
        # nobody is always the home side (or always the road side)
        for opp, v in venues.items():
            assert set(v) == {True, False}, (n_opps, seed, opp, v)
        assert sum(sum(v) for v in venues.values()) == sim.SEASON_GAMES // 2


def test_vs_league_extra_games_are_not_handed_out_alphabetically():
    extra_sets = set()
    for seed in range(6):
        games = sim.simulate_season_once(0.0, [0.0] * 30, np.random.default_rng(seed))["games"]
        counts = np.bincount([g[0] for g in games], minlength=30)
        extra_sets.add(tuple(np.flatnonzero(counts == 3)))
    assert tuple(range(22)) not in extra_sets
    assert len(extra_sets) > 1


def test_season_once_plays_the_projection_schedule():
    # Same seed, one sim: the projection and the single season must draw
    # the same schedule and the same margins.
    opps = list(np.linspace(-8, 8, 30))
    once = sim.simulate_season_once(2.0, opps, np.random.default_rng(4))
    proj = sim.simulate_vs_league(2.0, opps, np.random.default_rng(4), n_sims=1)
    assert once["wins"] == int(proj["wins"][0])


def test_different_seeds_give_different_seasons():
    # A net-0 team against a net-0 league is close to a coin flip per game,
    # so 20 seasons should spread like binomial(82, 1/2): sd about 4.5 wins
    # around 41. "More than one distinct total" would pass a simulator that
    # only ever produced 40 or 41 wins.
    wins = [
        sim.simulate_season_once(0.0, [0.0] * 29, np.random.default_rng(s))["wins"]
        for s in range(20)
    ]
    assert len(set(wins)) >= 8
    assert 3.0 <= np.std(wins) <= 7.0
    assert abs(np.mean(wins) - 41) <= 3


def test_same_seed_gives_identical_season():
    a = sim.simulate_season_once(1.0, [0.0] * 29, np.random.default_rng(9))
    b = sim.simulate_season_once(1.0, [0.0] * 29, np.random.default_rng(9))
    assert a == b


def test_roster_seed_is_order_independent_and_stable():
    assert sim.roster_seed([3, 1, 2]) == sim.roster_seed([2, 3, 1])
    assert sim.roster_seed([1, 2, 3]) != sim.roster_seed([1, 2, 4])
    assert isinstance(sim.roster_seed(["a", "b"]), int)
    assert 0 <= sim.roster_seed([1]) < 2**32


def test_soft_cap_is_monotone_and_bounded():
    xs = np.linspace(-60, 60, 241)
    capped = sim.soft_cap(xs)
    assert np.all(np.diff(capped) > 0)
    assert np.all(np.abs(capped) < sim.ABS_NET_CAP)
    assert sim.ABS_NET_KNEE == 10.0 and sim.ABS_NET_CAP == 16.0


def test_soft_cap_leaves_realistic_ratings_alone():
    xs = np.linspace(-sim.ABS_NET_KNEE, sim.ABS_NET_KNEE, 81)
    assert np.allclose(sim.soft_cap(xs), xs)
    assert sim.soft_cap(5.0) == 5.0
    assert sim.soft_cap(-10.0) == -10.0


def test_soft_cap_is_continuous_and_smooth_at_the_knee():
    eps = 1e-6
    k = sim.ABS_NET_KNEE
    assert sim.soft_cap(k + eps) == pytest.approx(k, abs=1e-5)
    # slope 1 on both sides of the knee
    above = (sim.soft_cap(k + 2 * eps) - sim.soft_cap(k + eps)) / eps
    assert above == pytest.approx(1.0, abs=1e-3)


def test_soft_cap_bends_the_best_ever_and_saturates_superteams():
    # the 1995-96 Bulls' +13.4-ish territory barely bends
    assert sim.soft_cap(13.65) == pytest.approx(13.3, abs=0.2)
    assert 15.5 < sim.soft_cap(40.0) < 16.0
    assert sim.soft_cap(-40.0) == pytest.approx(-sim.soft_cap(40.0))
    assert isinstance(sim.soft_cap(3.0), float)
    assert isinstance(sim.soft_cap(30.0), float)
