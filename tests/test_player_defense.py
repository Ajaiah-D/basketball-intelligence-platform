"""mart_player_defense: the defensive on/off estimate and fouls per 36.

The dbt test assert_player_defense_on_off_rules checks the null rules for
every player; these pin them to named players and recompute Jrue Holiday's
2024-25 estimate by hand from the published team and player ratings.
"""

import pytest

SEASON = "2024-25"
HOLIDAY = 201950


def _row(con, season, player_id):
    return con.execute(
        "select * from main_marts.mart_player_defense where season = ? and player_id = ?",
        [season, player_id],
    ).df()


def test_jrue_holiday_2024_25_matches_the_hand_calculation(con):
    """BOS allowed 110.1 over the season and 107.7 with Holiday on the
    floor for 1,901 of 82 x 48 minutes (share 0.48), so the other minutes
    averaged (110.1 - 0.48 x 107.7) / 0.52 = 112.3: on minus off = -4.6."""
    row = _row(con, SEASON, HOLIDAY).iloc[0]
    assert row["team_abbreviation"] == "BOS"
    assert row["on_court_def_rating"] == pytest.approx(107.7)
    assert row["team_def_rating"] == pytest.approx(110.1)
    assert row["team_games"] == 82
    assert row["minutes_share"] == pytest.approx(0.48, abs=0.01)
    share = row["minutes"] / (row["team_games"] * 48)
    by_hand = 107.7 - (110.1 - share * 107.7) / (1 - share)
    assert by_hand == pytest.approx(-4.6, abs=0.2)
    assert row["def_on_minus_off"] == pytest.approx(-4.6, abs=0.2)
    assert row["def_on_minus_off"] == pytest.approx(by_hand, abs=0.1)


def test_a_traded_player_has_no_on_off(con):
    traded = con.execute(
        """
        select d.def_on_minus_off, d.est_off_court_def_rating, d.on_court_def_rating
        from main_marts.mart_player_defense d
        join main_marts.mart_player_season s using (season, player_id)
        where d.season = ? and s.team_label like '%→%' and d.minutes >= 500
        """,
        [SEASON],
    ).df()
    assert len(traded) > 0
    assert traded["def_on_minus_off"].isna().all()
    assert traded["est_off_court_def_rating"].isna().all()


def test_few_minutes_or_no_official_rating_means_no_on_off(con):
    few, early = con.execute(
        """
        select
            count(*) filter (where minutes < 500 and def_on_minus_off is not null),
            count(*) filter (where season < '1996-97' and def_on_minus_off is not null)
        from main_marts.mart_player_defense
        """
    ).fetchone()
    assert few == 0
    assert early == 0


def test_enough_single_team_players_have_an_estimate(con):
    n = con.execute(
        "select count(*) from main_marts.mart_player_defense"
        " where season = ? and def_on_minus_off is not null",
        [SEASON],
    ).fetchone()[0]
    assert n > 200


def test_fouls_per_36_is_a_plausible_rate_and_null_below_100_minutes(con):
    low, bad, null_rows = con.execute(
        """
        select
            count(*) filter (where minutes < 100 and fouls_per_36 is not null),
            count(*) filter (where fouls_per_36 < 0 or fouls_per_36 > 15),
            count(*) filter (where minutes >= 100 and fouls_per_36 is null
                             and season >= '1996-97')
        from main_marts.mart_player_defense
        """
    ).fetchone()
    assert low == 0
    assert bad == 0
    assert null_rows == 0


def test_fouls_per_36_matches_the_game_logs(con):
    direct = con.execute(
        """
        select round(36.0 * sum(personal_fouls) / sum(minutes_played), 2)
        from main_staging.stg_player_game_logs
        where season = ? and player_id = ?
        """,
        [SEASON, HOLIDAY],
    ).fetchone()[0]
    assert _row(con, SEASON, HOLIDAY).iloc[0]["fouls_per_36"] == pytest.approx(direct)
