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

from dashboard.lib import sim  # noqa: E402


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
    assert sim.team_net_rating(negative, [2.0] * 8, 2.0, 0.0) == pytest.approx(
        2.0 * -5.0
    )
    positive = [1.0] * 8
    assert sim.team_net_rating(positive, [0.5] * 8, 2.0, 0.0) == pytest.approx(10.0)


def test_team_net_rating_rejects_wrong_roster_size():
    with pytest.raises(ValueError):
        sim.team_net_rating([1.0] * 7, [1.0] * 7, 2.0, 0.0)


def test_win_prob_basics():
    assert sim.win_prob(0, 0) == pytest.approx(0.5)
    assert sim.win_prob(5, 0) > 0.6
    assert sim.win_prob(0, 5) < 0.4
    assert sim.win_prob(0, 0, home_edge=sim.HOME_EDGE) > 0.5
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
    out = sim.simulate_vs_league(
        0.0, [0.0] * 29, np.random.default_rng(11), n_sims=2000
    )
    assert out["wins"].mean() == pytest.approx(41, abs=1.5)


def test_plus_five_team_wins_over_fifty():
    out = sim.simulate_vs_league(
        5.0, [0.0] * 29, np.random.default_rng(11), n_sims=2000
    )
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
    assert opp == 0 and is_home is True and won == (margin > 0)


def test_different_seeds_give_different_seasons():
    totals = {
        sim.simulate_season_once(0.0, [0.0] * 29, np.random.default_rng(s))["wins"]
        for s in range(20)
    }
    assert len(totals) > 1


def test_same_seed_gives_identical_season():
    a = sim.simulate_season_once(1.0, [0.0] * 29, np.random.default_rng(9))
    b = sim.simulate_season_once(1.0, [0.0] * 29, np.random.default_rng(9))
    assert a == b


def test_league_once_every_team_plays_82_and_one_champion():
    nets = [10.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    for seed in range(10):
        out = sim.simulate_league_once(nets, np.random.default_rng(seed))
        wins = np.asarray(out["wins"])
        assert len(wins) == 6
        assert out["games"] == [82] * 6
        assert (wins >= 0).all() and (wins <= 82).all()
        assert out["champion"] in range(6)
        finals = [s for s in out["bracket"] if s["round"] == "final"]
        assert len(finals) == 1
        assert finals[0]["winner"] == out["champion"]
        assert len(out["bracket"]) == 3
        for s in out["bracket"]:
            assert max(s["high_wins"], s["low_wins"]) == 4
            assert min(s["high_wins"], s["low_wins"]) <= 3
            assert s["winner"] in (s["high"], s["low"])


def test_league_schedule_gives_each_team_82_games_for_even_sizes():
    for n in (2, 4, 6, 8, 10):
        games = sim._schedule(n)
        totals = np.zeros(n, dtype=int)
        for (i, j), (hi, hj) in games.items():
            totals[i] += hi + hj
            totals[j] += hi + hj
        assert (totals == 82).all(), n


def test_league_schedule_home_away_is_near_even():
    games = sim._schedule(6)
    for hi, hj in games.values():
        assert abs(hi - hj) <= 1


def test_league_rejects_odd_team_counts():
    with pytest.raises(ValueError, match="even number of teams"):
        sim.simulate_league([0.0] * 5, np.random.default_rng(0), n_sims=10)
    with pytest.raises(ValueError, match="even number of teams"):
        sim.simulate_league_once([0.0] * 5, np.random.default_rng(0))


def test_league_rejects_two_teams_with_a_clear_message():
    with pytest.raises(ValueError, match="at least 4 teams"):
        sim.simulate_league([0.0, 0.0], np.random.default_rng(0), n_sims=10)
    with pytest.raises(ValueError, match="at least 4 teams"):
        sim.simulate_league_once([0.0, 0.0], np.random.default_rng(0))


def test_simulate_league_outputs_and_title_odds_sum_to_one():
    nets = [10.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    out = sim.simulate_league(nets, np.random.default_rng(4), n_sims=500)
    assert out["wins"].shape == (500, 6)
    assert (out["wins"].min() >= 0) and (out["wins"].max() <= 82)
    assert out["median_wins"].shape == (6,)
    assert out["title_odds"].sum() == pytest.approx(1.0, abs=1e-9)
    assert out["playoff_odds"].shape == (6,)
    # Four of six make the playoffs, every sim.
    assert out["playoff_odds"].sum() == pytest.approx(4.0, abs=1e-9)
    assert out["title_odds"].argmax() == 0
    assert out["playoff_odds"][0] > 0.95


def test_simulate_league_is_deterministic_for_a_seed():
    nets = [3.0, 1.0, 0.0, -1.0, -2.0, 4.0]
    a = sim.simulate_league(nets, np.random.default_rng(8), n_sims=100)
    b = sim.simulate_league(nets, np.random.default_rng(8), n_sims=100)
    assert np.array_equal(a["wins"], b["wins"])
    assert np.array_equal(a["title_odds"], b["title_odds"])


def test_equal_teams_have_equal_title_odds_roughly():
    out = sim.simulate_league([0.0] * 6, np.random.default_rng(6), n_sims=3000)
    assert out["title_odds"].min() > 0.08
    assert out["title_odds"].max() < 0.26


def test_roster_seed_is_order_independent_and_stable():
    assert sim.roster_seed([3, 1, 2]) == sim.roster_seed([2, 3, 1])
    assert sim.roster_seed([1, 2, 3]) != sim.roster_seed([1, 2, 4])
    assert isinstance(sim.roster_seed(["a", "b"]), int)
    assert 0 <= sim.roster_seed([1]) < 2**32
