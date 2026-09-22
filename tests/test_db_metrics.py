"""Regression tests for the SQL in dashboard/lib/db.py.

The app computes some rate stats independently of the dbt marts so the
dashboard still works when the marts are absent. That independence is
deliberate, but it lets the two implementations drift - these tests pin
them together.
"""

import pytest

# Seasons where a meaningful share of player-game rows have a null in one
# of the three columns the true-shooting ratio sums. Not every player in
# these seasons is affected - only those whose own games hit the null - so
# the tests below check the mechanism per player, not the whole season.
INCOMPLETE_SEASONS = ["1979-80", "1984-85"]
COMPLETE_SEASON = "2024-25"

TS_SQL = """
    select
        player_id,
        case when count(*) filter (
                 where field_goals_attempted is null
                    or free_throws_attempted is null
                    or points is null) > 0
             then null
             else round(sum(points) / nullif(2 * (sum(field_goals_attempted)
                  + 0.44 * sum(free_throws_attempted)), 0) * 100, 1)
        end as ts_pct
    from main_staging.stg_player_game_logs
    where season = ?
    group by player_id
    having count(*) >= 40
"""

# One column at a time, so the query stays readable independently of TS_SQL.
_NULL_RATIO_INPUT = """
    field_goals_attempted is null
    or free_throws_attempted is null
    or points is null
"""


@pytest.mark.parametrize("season", INCOMPLETE_SEASONS)
def test_true_shooting_is_null_for_players_with_a_null_ratio_input(con, season):
    """The direct bug: sum() skips a null denominator term while the
    numerator still counts that game's points. Any player whose own games
    hit this must show no TS%, full stop."""
    affected = con.execute(
        f"""
        select player_id from main_staging.stg_player_game_logs
        where season = ?
        group by player_id
        having count(*) >= 40 and sum(case when {_NULL_RATIO_INPUT} then 1 else 0 end) > 0
        """,
        [season],
    ).fetchall()
    assert affected, f"expected at least one affected player in {season}"
    affected_ids = {row[0] for row in affected}

    computed = dict(con.execute(TS_SQL, [season]).fetchall())
    offenders = [(pid, computed[pid]) for pid in affected_ids if computed.get(pid) is not None]
    assert not offenders, (
        f"{season}: players with a null ratio input still got a TS%: {offenders[:3]}"
    )


@pytest.mark.parametrize("season", INCOMPLETE_SEASONS)
def test_true_shooting_is_correct_for_players_with_no_null_ratio_input(con, season):
    """Players whose own games are fully populated must still get a real
    number - the guard must catch the bug without discarding good data -
    and that number must match an independent recomputation from the raw
    rows, not just "be non-null"."""
    clean_ids = con.execute(
        f"""
        select player_id from main_staging.stg_player_game_logs
        where season = ?
        group by player_id
        having count(*) >= 40 and sum(case when {_NULL_RATIO_INPUT} then 1 else 0 end) = 0
        limit 5
        """,
        [season],
    ).fetchall()
    assert clean_ids, f"expected at least one fully-populated player in {season}"

    computed = dict(con.execute(TS_SQL, [season]).fetchall())
    for (player_id,) in clean_ids:
        raw = con.execute(
            """
            select points, field_goals_attempted, free_throws_attempted
            from main_staging.stg_player_game_logs
            where season = ? and player_id = ?
            """,
            [season, player_id],
        ).fetchdf()
        expected = round(
            100 * raw["points"].sum()
            / (2 * (raw["field_goals_attempted"].sum() + 0.44 * raw["free_throws_attempted"].sum())),
            1,
        )
        got = computed.get(player_id)
        assert got is not None, f"{season} player {player_id}: expected a value, got null"
        assert got == pytest.approx(expected, abs=0.05), (
            f"{season} player {player_id}: got {got}, independently computed {expected}"
        )


def test_true_shooting_matches_mart_when_box_score_complete(con):
    """Where both compute a value, the app and the mart must agree exactly."""
    rows = con.execute(
        f"""
        with app as ({TS_SQL})
        select a.player_id, a.ts_pct, m.true_shooting_pct
        from app a
        join main_marts.mart_player_season m
          on m.player_id = a.player_id and m.season = ?
        where a.ts_pct is not null and m.true_shooting_pct is not null
        """,
        [COMPLETE_SEASON, COMPLETE_SEASON],
    ).fetchall()
    assert len(rows) > 100, "expected a substantial overlap to compare"
    mismatches = [r for r in rows if abs(r[1] - r[2]) > 0.05]
    assert not mismatches, f"app/mart TS% drift: {mismatches[:5]}"
