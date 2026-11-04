"""mart_player_percentiles: who qualifies (it must match the dashboard's
Python rule), and the percentile rules the scatter and compare views rely on.

The dbt test assert_player_percentiles checks direction and range for every
season; these pin the same rules to named facts and recompute a percentile
independently in pandas. The Player tab's shooting ranks, and the chart that
labels them, are at the end.
"""

import re
from pathlib import Path

import pandas as pd
import pytest

from dashboard.lib import viz
from dashboard.lib.data import players as player_data
from dashboard.lib.stats import ShootingRank, qualification_threshold
from dashboard.views.players import player

SEASON = "2024-25"
DBT_TESTS = Path(__file__).resolve().parents[1] / "dbt" / "basketball_intelligence" / "tests"


def _players(con, season):
    return con.execute(
        "select * from main_marts.mart_player_percentiles where season = ?", [season]
    ).df()


def test_qualification_matches_the_dashboard_rule_in_every_season(con):
    """The mart ports dashboard/lib/stats.py::qualification_threshold into
    SQL; both must give the same threshold for each season in the warehouse
    (the fixtures carry four, a full warehouse every one). Every finished
    season is at the 25 cap; the scaled branch is covered by the next test."""
    games = con.execute("select season, games_played as gp from main_marts.mart_player_season").df()
    mart = con.execute(
        "select season, min(qualification_games) as lo, max(qualification_games) as hi"
        " from main_marts.mart_player_percentiles group by season"
    ).df()
    assert len(mart) >= 3
    for row in mart.itertuples():
        expected = qualification_threshold(games[games["season"] == row.season])
        assert row.lo == row.hi == expected, row.season


def test_sql_rule_cases_equal_the_python_rule():
    """assert_qualification_games_rule applies the SQL macro to made-up season
    lengths (the real seasons are all at the 25 cap, so the scaled branch
    would otherwise go untested). The expected answers it holds must be what
    the Python rule gives, or the two have drifted apart."""
    sql = (DBT_TESTS / "assert_qualification_games_rule.sql").read_text(encoding="utf-8")
    cases = [(int(a), int(b)) for a, b in re.findall(r"\((\d+),\s*(\d+)\)", sql)]
    assert [gp for gp, _ in cases] == [1, 3, 5, 9, 10, 30, 41, 42, 82]
    for max_gp, expected in cases:
        assert qualification_threshold(pd.DataFrame({"gp": [1, max_gp]})) == expected, max_gp


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


# --- The Player tab's shooting ranks -------------------------------------------------


@pytest.mark.full_warehouse
def test_shooting_ranks_carry_attempts_and_the_league_average(con):
    season = "2025-26"
    stats = player_data.player_season_stats(season)
    row = stats[stats["player"] == "Luka Dončić"].iloc[0]
    league = player_data.league_shooting_averages(season)
    ranks = {r.label: r for r in player.shooting_percentiles(season, row)}
    assert list(ranks) == ["FG%", "3P%", "FT%", "TS%"]
    assert all(isinstance(r, ShootingRank) for r in ranks.values())
    fg = ranks["FG%"]
    assert fg.value == pytest.approx(row["fg_pct"])
    assert fg.attempts_pg == pytest.approx(row["fga_pg"])
    assert fg.league == pytest.approx(league["fg_pct"])
    assert ranks["3P%"].attempts_pg == pytest.approx(row["tpa_pg"])
    assert ranks["3P%"].league == pytest.approx(league["fg3_pct"])
    assert ranks["FT%"].attempts_pg == pytest.approx(row["fta_pg"])
    # True shooting counts field goals and free throws together, and the
    # league table has no figure for it: neither part is invented.
    assert ranks["TS%"].attempts_pg is None and ranks["TS%"].league is None
    assert 0 <= fg.percentile <= 100


def test_shooting_ranks_skip_a_stat_under_its_attempts_floor():
    # 99 free throws is one short of the 100 the FT% rank asks for.
    row = pd.Series(
        {
            "fg_pct": 50.0,
            "fga_total": 400,
            "fga_pg": 10.0,
            "fg3_pct": 35.0,
            "tpa_total": 150,
            "tpa_pg": 3.0,
            "ft_pct": 80.0,
            "fta_total": 99,
            "fta_pg": 2.0,
            "ts_pct": 58.0,
        }
    )
    ranks = player.rank_shooting(row, _shooting_pool(), _league())
    assert [r.label for r in ranks] == ["FG%", "3P%", "TS%"]


def _shooting_pool() -> pd.DataFrame:
    """Three players a full season in (70 games)."""
    return pd.DataFrame(
        {
            "gp": [70, 70, 70],
            "fg_pct": [40.0, 45.0, 55.0],
            "fga_total": [500, 500, 500],
            "fg3_pct": [30.0, 36.0, 40.0],
            "tpa_total": [200, 200, 200],
            "ft_pct": [70.0, 75.0, 90.0],
            "fta_total": [200, 200, 200],
            "ts_pct": [52.0, 56.0, 62.0],
        }
    )


def _league() -> pd.Series:
    return pd.Series({"fg_pct": 47.0, "fg3_pct": 36.0, "ft_pct": 78.0})


def test_the_attempts_floors_scale_down_early_in_a_season():
    # Ten games in, the games floor is 6 of a full season's 25 (stats.
    # qualification_threshold): the attempts floors ask the same share.
    early = _shooting_pool().assign(gp=10)
    assert player.shooting_floors(early) == {"FG%": 72, "3P%": 24, "FT%": 24, "TS%": 72}
    full = {"FG%": 300, "3P%": 100, "FT%": 100, "TS%": 300}
    assert player.shooting_floors(_shooting_pool()) == full
    row = pd.Series({"fg_pct": 50.0, "fga_total": 80, "fga_pg": 8.0, "ts_pct": 58.0})
    assert [r.label for r in player.rank_shooting(row, early, _league())] == ["FG%", "TS%"]
    assert player.rank_shooting(row, _shooting_pool(), _league()) == []


def test_a_league_without_figures_drops_that_part_of_the_label():
    # A season the league table lacks comes back all NaN.
    row = pd.Series(
        {"fg_pct": 50.0, "fga_total": 400, "fga_pg": 10.0, "ts_pct": 58.0, "tpa_total": 0}
    )
    league = pd.Series({"fg_pct": float("nan"), "fg3_pct": float("nan"), "ft_pct": float("nan")})
    ranks = player.rank_shooting(row, _shooting_pool(), league)
    assert ranks[0].league is None


def test_shooting_percentiles_chart_labels():
    fig = viz.shooting_percentiles_chart(
        [
            ShootingRank("FG%", 61.2, 47.6, 22.8, 47.0),
            ShootingRank("TS%", 80.4, 61.3, None, None),
        ]
    )
    labelled = [list(t.text) for t in fig.data if t.text is not None]
    assert labelled == [["47.6 on 22.8/g · league 47.0 · 61st", "61.3 · 80th"]]
