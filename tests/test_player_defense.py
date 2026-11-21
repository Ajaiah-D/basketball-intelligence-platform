"""mart_player_defense: defensive on/off and fouls per 36.

The dbt test assert_player_defense_on_off_rules checks the on/off rules for
every player; these pin them to named players: Jrue Holiday's and Zach
LaVine's official 2024-25 on/off recomputed from the NBA's on and off
ratings, and Tim Duncan's 2002-03 estimate by hand from the published team
and player ratings.
"""

import pytest

SEASON = "2024-25"
HOLIDAY = 201950
LAVINE = 203897
DUNCAN = 1495


def _row(con, season, player_id):
    return con.execute(
        "select * from main_marts.mart_player_defense where season = ? and player_id = ?",
        [season, player_id],
    ).df()


def test_jrue_holiday_2024_25_is_the_nbas_on_off(con):
    """BOS allowed 107.7 with Holiday on the floor (1,896 minutes) and
    110.5 with him off (2,070): on minus off = -2.8."""
    row = _row(con, SEASON, HOLIDAY).iloc[0]
    assert row["on_off_source"] == "official"
    assert row["est_off_court_def_rating"] == pytest.approx(110.5)
    assert row["def_on_minus_off"] == pytest.approx(-2.8)


def test_a_traded_player_gets_the_minutes_weighted_on_off(con):
    """LaVine played 1,432 on-court minutes for CHI (114.4 on, 113.8 off)
    and 1,170 for SAC (119.9 on, 107.8 off): (1432 x 0.6 + 1170 x 12.1) /
    2602 = 5.8."""
    row = _row(con, SEASON, LAVINE).iloc[0]
    assert row["on_off_source"] == "official"
    stints = con.execute(
        "select on_minutes, on_def_rating, off_def_rating from main_staging.stg_player_on_off"
        " where season = ? and player_id = ?",
        [SEASON, LAVINE],
    ).fetchall()
    assert len(stints) == 2
    by_hand = sum(m * (on - off) for m, on, off in stints) / sum(m for m, _, _ in stints)
    assert by_hand == pytest.approx(5.8, abs=0.05)
    assert row["def_on_minus_off"] == pytest.approx(by_hand, abs=0.05)


@pytest.mark.full_warehouse
def test_tim_duncan_2002_03_matches_the_estimate_by_hand(con):
    """Before 2007-08 there is no NBA on/off. SAS allowed 98.1 over the
    season and 96.4 with Duncan on the floor for 3,183 of 82 x 48 minutes
    (share 0.809), so the other minutes averaged (98.1 - 0.809 x 96.4) /
    0.191 = 105.3: on minus off = -8.9."""
    row = _row(con, "2002-03", DUNCAN).iloc[0]
    assert row["on_off_source"] == "estimate"
    share = row["minutes"] / (row["team_games"] * 48)
    by_hand = row["on_court_def_rating"] - (
        row["team_def_rating"] - share * row["on_court_def_rating"]
    ) / (1 - share)
    assert by_hand == pytest.approx(-8.9, abs=0.1)
    assert row["def_on_minus_off"] == pytest.approx(by_hand, abs=0.1)


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


def test_enough_players_have_on_off(con):
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
