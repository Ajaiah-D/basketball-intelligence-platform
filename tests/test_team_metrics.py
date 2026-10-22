import pandas as pd

from dashboard.lib import team_metrics as tm


def _adv():
    return pd.DataFrame(
        {
            "team_abbreviation": ["AAA", "BBB", "CCC"],
            "offensive_rating": [118.0, 112.0, None],
            "defensive_rating": [110.0, 108.0, 115.0],
        }
    )


def test_league_rank_respects_direction_and_skips_missing():
    adv = _adv()
    assert tm.league_rank(adv, "AAA", "offensive_rating", higher_is_better=True) == (1, 2)
    # Defense: lower allowed is better, so BBB's 108 ranks first.
    assert tm.league_rank(adv, "BBB", "defensive_rating", higher_is_better=False) == (1, 3)
    assert tm.league_rank(adv, "CCC", "offensive_rating", higher_is_better=True) is None


def test_four_factors_table_ranks_offense_and_defense():
    adv = pd.DataFrame(
        {
            "team_abbreviation": ["AAA", "BBB"],
            "effective_fg_pct": [56.0, 52.0],
            "opp_effective_fg_pct": [55.0, 51.0],
            "turnover_pct": [12.0, 14.0],
            "opp_turnover_pct": [13.0, 15.0],
            "offensive_rebound_pct": [25.0, 30.0],
            "defensive_rebound_pct": [70.0, 75.0],
            "free_throw_rate": [20.0, 24.0],
            "opp_free_throw_rate": [19.0, 23.0],
        }
    )
    table = tm.four_factors(adv, "AAA").set_index("factor")
    shooting = table.loc["Shooting"]
    assert shooting["offense"] == 56.0 and shooting["offense_rank"] == "1st"
    assert shooting["defense"] == 55.0 and shooting["defense_rank"] == "2nd"  # allowed more
    assert shooting["league_offense"] == 54.0
    assert table.loc["Turnovers", "offense_rank"] == "1st"  # fewer is better
    assert table.loc["Turnovers", "defense_rank"] == "2nd"  # BBB forces more, which is better
    assert table.loc["Free throws", "defense_rank"] == "1st"  # fouling less is better


def _games():
    # Oldest first, as data.teams.team_game_log returns it.
    return pd.DataFrame(
        {
            "game_date": pd.date_range("2026-01-01", periods=6),
            "is_away_game": [False, True, False, True, False, True],
            "is_win": [True, False, True, True, True, False],
            "points": [110, 100, 105, 120, 99, 90],
            "opp_points": [100, 104, 103, 100, 97, 112],
            "opponent": ["GOOD", "BAD", "GOOD", "BAD", "GOOD", "GOOD"],
        }
    )


def test_splits():
    standings = pd.DataFrame({"team": ["GOOD", "BAD"], "pct": [0.650, 0.300]})
    s = tm.splits(_games(), standings)
    assert s["home"] == "3-0" and s["away"] == "1-2"
    assert s["last10"] == "4-2"  # fewer than ten played: all of them
    assert s["streak"] == "L1"
    assert s["close"] == "2-1"  # margins 2, 2 (wins) and 4 (loss)
    assert s["vs_winning"] == "3-1"  # GOOD finished above .500


def test_streak_counts_the_current_run():
    games = _games().assign(is_win=[False, True, False, True, True, True])
    assert tm.splits(games, pd.DataFrame({"team": [], "pct": []}))["streak"] == "W3"


def test_move_note_describes_a_mid_season_trade():
    assert tm.move_note("CHI → BOS", "BOS") == "from CHI"
    assert tm.move_note("CHI → BOS", "CHI") == "to BOS"
    assert tm.move_note("WAS → ATL → MIL", "ATL") == "from WAS, to MIL"
    assert tm.move_note("BOS", "BOS") == ""
    assert tm.move_note(None, "BOS") == ""
