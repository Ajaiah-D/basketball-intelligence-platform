"""mart_player_percentiles: who qualifies (it must match the dashboard's
Python rule), and the percentile rules the scatter and compare views rely on.

The dbt test assert_player_percentiles checks direction and range for every
season; these pin the same rules to named facts and recompute a percentile
independently in pandas.
"""

import pandas as pd
import pytest

from dashboard.lib.stats import qualification_threshold

SEASON = "2024-25"


def _players(con, season):
    return con.execute(
        "select * from main_marts.mart_player_percentiles where season = ?", [season]
    ).df()


def test_qualification_matches_the_dashboard_rule_in_every_season(con):
    """The mart ports dashboard/lib/stats.py::qualification_threshold into
    SQL; both must give the same threshold for each season in the warehouse
    (the fixtures carry four, a full warehouse every one)."""
    games = con.execute("select season, games_played as gp from main_marts.mart_player_season").df()
    mart = con.execute(
        "select season, min(qualification_games) as lo, max(qualification_games) as hi"
        " from main_marts.mart_player_percentiles group by season"
    ).df()
    assert len(mart) >= 3
    for row in mart.itertuples():
        expected = qualification_threshold(games[games["season"] == row.season])
        assert row.lo == row.hi == expected, row.season


def test_the_python_rule_scales_below_the_cap_like_the_sql():
    """A season cut short (the live one) lowers the threshold; pin the
    arithmetic the SQL repeats: 60% of the most games, rounded down."""
    assert qualification_threshold(pd.DataFrame({"gp": [1, 30]})) == 18
    assert qualification_threshold(pd.DataFrame({"gp": [1, 82]})) == 25


def test_only_qualified_players_are_graded(con):
    players = _players(con, SEASON)
    assert players["is_qualified"].any() and not players["is_qualified"].all()
    assert (
        players["is_qualified"] == (players["games_played"] >= players["qualification_games"])
    ).all()
    graded = players["points_per_game_pctile"].notna()
    assert (graded == players["is_qualified"]).all()
    # Non-qualified players keep their row and their values.
    assert players.loc[~players["is_qualified"], "points_per_game"].notna().all()


def test_percentile_is_percent_rank_among_the_qualified(con):
    players = _players(con, SEASON)
    qualified = players[players["is_qualified"]]
    expected = 100 * (qualified["points_per_game"].rank(method="min") - 1) / (len(qualified) - 1)
    assert (qualified["points_per_game_pctile"] - expected).abs().max() < 0.05
    assert qualified["points_per_game_pctile"].min() == 0
    assert qualified["points_per_game_pctile"].max() == 100


def test_turnover_rate_is_graded_the_other_way(con):
    qualified = _players(con, SEASON).query("is_qualified")
    careful = qualified.loc[qualified["turnover_pct"].idxmin()]
    sloppy = qualified.loc[qualified["turnover_pct"].idxmax()]
    assert careful["turnover_pct_pctile"] > 99
    assert sloppy["turnover_pct_pctile"] == 0
    # The other measures are higher-is-better.
    top_scorer = qualified.loc[qualified["points_per_game"].idxmax()]
    assert top_scorer["points_per_game_pctile"] == 100


@pytest.mark.parametrize("season", ["1979-80", "1984-85"])
def test_early_seasons_have_no_percentile_for_missing_stats(con, season):
    """Box scores before 1985-86 lack the inputs; a null stat is not graded."""
    players = _players(con, season)
    assert len(players) > 0
    assert players["usage_pct"].isna().all()
    assert players["usage_pct_pctile"].isna().all()
