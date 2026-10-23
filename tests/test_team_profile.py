"""mart_team_profile: the new three-point values against the game logs, and
the rank and percentile rules a reader of the diagnosis views relies on.

The dbt tests (assert_team_profile_ranks) check every stat in every season;
these pin the same rules to named facts, and recompute the one set of
numbers the mart does not copy from mart_team_season.
"""

import pytest

SEASON = "2024-25"
# Seasons whose box scores lack three-point attempts, so the new values
# must be null rather than computed from a fraction of the games.
NO_THREE_POINT_ATTEMPTS = ["1979-80", "1984-85"]


def _profile(con, season):
    return con.execute("select * from main_marts.mart_team_profile where season = ?", [season]).df()


def test_one_row_per_team_season_in_mart_team_season(con):
    profile_rows, season_rows = con.execute(
        """
        select
            (select count(*) from main_marts.mart_team_profile),
            (select count(*) from main_marts.mart_team_season)
        """
    ).fetchone()
    assert profile_rows == season_rows


def test_three_point_values_match_the_game_logs(con):
    """Recomputed from the raw team game logs with the opponent's row found
    by game id, independently of the mart's own join."""
    direct = con.execute(
        """
        select
            t.team_id,
            round(100.0 * sum(t.three_pointers_made) / sum(t.three_pointers_attempted), 1)
                as three_pt_pct,
            round(100.0 * sum(t.three_pointers_attempted) / sum(t.field_goals_attempted), 1)
                as three_pt_rate,
            round(100.0 * sum(o.three_pointers_made) / sum(o.three_pointers_attempted), 1)
                as opp_three_pt_pct,
            round(100.0 * sum(o.three_pointers_attempted) / sum(o.field_goals_attempted), 1)
                as opp_three_pt_rate
        from main_staging.stg_team_game_logs t
        join main_staging.stg_team_game_logs o
          on o.game_id = t.game_id and o.team_id <> t.team_id
        where t.season = ?
        group by t.team_id
        """,
        [SEASON],
    ).df()
    profile = _profile(con, SEASON)
    merged = profile.merge(direct, on="team_id", suffixes=("", "_direct"))
    assert len(merged) == len(profile) == 30
    for col in ["three_pt_pct", "three_pt_rate", "opp_three_pt_pct", "opp_three_pt_rate"]:
        assert merged[col].notna().all()
        assert (merged[col] - merged[f"{col}_direct"]).abs().max() < 1e-9, col
    # Sanity on the scale: percentages, not fractions, and a modern shot mix.
    assert profile["three_pt_pct"].min() > 30 and profile["three_pt_pct"].max() < 45
    assert profile["three_pt_rate"].min() > 30 and profile["three_pt_rate"].max() < 60


@pytest.mark.parametrize("season", NO_THREE_POINT_ATTEMPTS)
def test_early_seasons_have_null_values_and_null_ranks(con, season):
    profile = _profile(con, season)
    assert len(profile) > 0
    for col in ["three_pt_pct", "three_pt_rate", "opp_three_pt_pct", "opp_three_pt_rate"]:
        assert profile[col].isna().all(), col
        assert profile[f"{col}_rank"].isna().all(), col
        assert profile[f"{col}_pctile"].isna().all(), col


def test_best_team_is_rank_one_in_the_right_direction(con):
    profile = _profile(con, SEASON)
    top_offense = profile.loc[profile["offensive_rating"].idxmax()]
    assert top_offense["offensive_rating_rank"] == 1
    assert top_offense["offensive_rating_pctile"] == 100
    # Lower is better for turnovers and for defense.
    fewest_turnovers = profile.loc[profile["turnover_pct"].idxmin()]
    assert fewest_turnovers["turnover_pct_rank"] == 1
    best_defense = profile.loc[profile["defensive_rating"].idxmin()]
    assert best_defense["defensive_rating_rank"] == 1
    # Style stats rank the largest value first.
    fastest = profile.loc[profile["pace"].idxmax()]
    assert fastest["pace_rank"] == 1
    most_threes = profile.loc[profile["three_pt_rate"].idxmax()]
    assert most_threes["three_pt_rate_rank"] == 1


def test_percentile_follows_rank_and_the_worst_team_sits_at_zero(con):
    profile = _profile(con, SEASON)
    teams = profile["offensive_rating"].notna().sum()
    expected = 100 * (1 - (profile["offensive_rating_rank"] - 1) / (teams - 1))
    assert (profile["offensive_rating_pctile"] - expected).abs().max() < 0.05
    assert profile["offensive_rating_pctile"].min() == 0
    assert profile["offensive_rating_rank"].max() <= teams


def test_ties_share_a_rank(con):
    """Values are rounded to a tenth, so some pair of teams ties on at
    least one stat; the tied teams must have the same rank and percentile."""
    tied = con.execute(
        """
        select count(*) from (
            select season, effective_fg_pct, count(*) as n,
                   count(distinct effective_fg_pct_rank) as ranks,
                   count(distinct effective_fg_pct_pctile) as pctiles
            from main_marts.mart_team_profile
            where effective_fg_pct is not null
            group by season, effective_fg_pct
            having count(*) > 1 and (count(distinct effective_fg_pct_rank) > 1
                                  or count(distinct effective_fg_pct_pctile) > 1)
        )
        """
    ).fetchone()[0]
    assert tied == 0
