"""Elo is the model's baseline and its only real signal in week one, so its
arithmetic is pinned directly rather than only through the pipeline."""

import pandas as pd
import pytest

from ml.elo import compute_elo, expected_score


def test_equal_ratings_are_a_coin_flip():
    assert expected_score(1500, 1500) == pytest.approx(0.5)


def test_four_hundred_points_is_ten_to_one():
    assert expected_score(1900, 1500) == pytest.approx(10 / 11, abs=1e-6)


def test_ratings_start_at_1500_and_are_pre_game():
    games = pd.DataFrame({
        "game_id": ["1", "2"],
        "season": ["2000-01", "2000-01"],
        "game_date": pd.to_datetime(["2000-11-01", "2000-11-03"]),
        "home_team_id": [10, 10],
        "away_team_id": [20, 20],
        "home_won": [True, True],
    })
    out = compute_elo(games).set_index("game_id")
    assert out.loc["1", "home_elo_pre"] == pytest.approx(1500.0)
    assert out.loc["1", "away_elo_pre"] == pytest.approx(1500.0)
    # After a home win the home side must be rated higher going into game 2.
    assert out.loc["2", "home_elo_pre"] > out.loc["2", "away_elo_pre"]


def test_ratings_regress_toward_the_mean_between_seasons():
    games = pd.DataFrame({
        "game_id": ["1", "2"],
        "season": ["2000-01", "2001-02"],
        "game_date": pd.to_datetime(["2001-01-01", "2001-11-01"]),
        "home_team_id": [10, 10],
        "away_team_id": [20, 20],
        "home_won": [True, True],
    })
    carried = compute_elo(games, carry=0.75).set_index("game_id")
    gain = carried.loc["2", "home_elo_pre"] - 1500.0
    full = compute_elo(games, carry=1.0).set_index("game_id")
    full_gain = full.loc["2", "home_elo_pre"] - 1500.0
    assert 0 < gain < full_gain, "carry must shrink the rating toward 1500"


def test_neutral_site_games_get_no_home_advantage():
    """fct_team_game assigns a neutral game's 'home' side by an arbitrary
    tiebreak (lower team_id), not a real home court. Applying the +100
    home-court term there would fabricate an advantage neither team has -
    confirmed as a real case in Task 4 (10 NBA Cup / international games).

    Isolate the effect on a single game: team 10 beats team 20 as the
    Elo-assigned "home" side, both starting at 1500. A real home win is
    expected to win more often (home + 100 vs away), so it earns a smaller
    rating bump than a neutral win (both sides plain 1500) for the same K.
    """
    base_game = {
        "game_id": ["1"], "season": ["2000-01"],
        "game_date": pd.to_datetime(["2000-11-01"]),
        "home_team_id": [10], "away_team_id": [20], "home_won": [True],
    }
    # compute_elo only returns pre-game ratings, so to observe a post-game
    # rating, read the PRE-game rating of a second game for the same team.
    second_game = {
        "game_id": ["2"], "season": ["2000-01"],
        "game_date": pd.to_datetime(["2000-11-03"]),
        "home_team_id": [10], "away_team_id": [30], "home_won": [False],
        "is_neutral_site": [False],
    }
    neutral_then_second = compute_elo(pd.concat(
        [pd.DataFrame({**base_game, "is_neutral_site": [True]}), pd.DataFrame(second_game)],
        ignore_index=True,
    ))
    home_then_second = compute_elo(pd.concat(
        [pd.DataFrame({**base_game, "is_neutral_site": [False]}), pd.DataFrame(second_game)],
        ignore_index=True,
    ))
    rating_after_neutral_win = neutral_then_second.set_index("game_id").loc["2", "home_elo_pre"]
    rating_after_real_home_win = home_then_second.set_index("game_id").loc["2", "home_elo_pre"]

    assert rating_after_neutral_win == pytest.approx(1500.0 + 20 * (1.0 - 0.5))
    assert rating_after_real_home_win == pytest.approx(
        1500.0 + 20 * (1.0 - expected_score(1600.0, 1500.0))
    )
    assert rating_after_neutral_win > rating_after_real_home_win, (
        "a neutral win (expected 50/50) must earn a bigger rating bump than "
        "a real home win (expected to win more often) for the same K - if "
        "these are equal, the home-court term was not suppressed for the "
        "neutral game"
    )


def test_missing_is_neutral_site_column_defaults_to_all_regular_games():
    """Callers that don't pass the column (e.g. an older caller, or a test
    fixture with no neutral games) must get today's regular behavior, not
    an error.

    Not raising is not enough: a single game's pre-game rating is 1500/1500
    whatever home-court term applies, so it cannot tell a correct default
    from an inverted guard. Use a second game for the same team to observe
    the post-game rating, and pin it to the real-home-win value - i.e. the
    +100 term was applied, not suppressed.
    """
    games = pd.DataFrame({
        "game_id": ["1", "2"],
        "season": ["2000-01", "2000-01"],
        "game_date": pd.to_datetime(["2000-11-01", "2000-11-03"]),
        "home_team_id": [10, 10],
        "away_team_id": [20, 30],
        "home_won": [True, False],
    })
    out = compute_elo(games)  # must not raise
    assert len(out) == 2
    assert out.set_index("game_id").loc["2", "home_elo_pre"] == pytest.approx(
        1500.0 + 20 * (1.0 - expected_score(1600.0, 1500.0))
    )
