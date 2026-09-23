"""Regression tests for the SQL in dashboard/lib/db.py.

The app computes some rate stats independently of the dbt marts so the
dashboard still works when the marts are absent. That independence is
deliberate, but it lets the two implementations drift - these tests pin
them together.
"""

import duckdb
import pytest

from dashboard.lib import db

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


# --- Finances page coverage ----------------------------------------------------
#
# The tmp_warehouse_without_marts / warehouse_with_finances_mart fixtures
# these use live in conftest.py, because tests/test_finances_page.py drives
# the same page end-to-end against the same warehouse shape and the two
# definitions would otherwise drift apart.

def test_team_finances_available_false_before_mart_exists(tmp_warehouse_without_marts):
    assert db.team_finances_available() is False


def test_team_payroll_history_filters_by_team(warehouse_with_finances_mart):
    df = db.team_payroll_history(team="BOS")
    assert (df["team_abbreviation"] == "BOS").all()
    assert len(df) > 0


def test_team_payroll_history_merges_a_renamed_franchise(warehouse_with_finances_mart):
    """GOS and GSW are one franchise under nba_api's 1996-97 code rename, so
    asking for GSW must return the GOS seasons too.

    Before this, the Finances page - whose whole point is 42 years of one
    team's history - listed the two halves as separate teams and silently
    started the Warriors chart in 1996-97. Asserting both codes come back
    (not just a row count) is what would catch a regression that resolved
    the franchise but then filtered them back apart."""
    df = db.team_payroll_history(team="GSW")
    assert set(df["team_abbreviation"]) == {"GOS", "GSW"}, (
        "GSW must return both of this franchise's abbreviations"
    )
    # One continuous series, oldest first - the chart plots it in this order.
    assert df["season"].tolist() == sorted(df["season"].tolist())
    assert df["season"].tolist() == ["1995-96", "1996-97"]


def test_team_payroll_history_does_not_merge_an_unrelated_team(warehouse_with_finances_mart):
    """Only the four code-rename pairs merge. A relocation (SEA -> OKC) or
    any ordinary code must still return exactly itself, or the fix would be
    inventing franchise history instead of repairing it."""
    for code in ("BOS", "NYK", "MIA", "DEN"):
        df = db.team_payroll_history(team=code)
        assert set(df["team_abbreviation"]) == {code}, code
    assert db.franchise_codes("SEA") == ("SEA",)
    assert db.franchise_codes("OKC") == ("OKC",)


def test_franchise_options_collapses_only_the_renamed_pairs(warehouse_with_finances_mart):
    codes = db.team_payroll_history()["team_abbreviation"]
    options = db.franchise_options(codes)
    assert "GOS" not in options, "the legacy code must not be offered separately"
    assert "GSW" in options
    # Everything else survives untouched.
    assert {"BOS", "NYK", "MIA", "DEN"} <= set(options)


def test_salary_cap_history_has_no_apron_before_2023_24(warehouse_with_finances_mart):
    df = db.salary_cap_history()
    pre_apron = df[df["season"] < "2023-24"]
    assert pre_apron["first_apron"].isna().all()
