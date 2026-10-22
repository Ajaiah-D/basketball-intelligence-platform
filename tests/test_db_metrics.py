"""Regression tests for the dashboard's data access.

The player pages read the dbt player marts through dashboard/lib/data;
until Task 12 they ran their own queries over the game logs. The tests
below keep those queries as the reference and pin the new functions to
them, frame for frame. Also here: the true-shooting null rule, and the
finances and advanced queries.
"""

import duckdb
import pandas as pd
import pytest

from dashboard.lib.data import advanced, finances, players, seasons
from dashboard.lib.data import arcade as arcade_data
from dashboard.lib.data import core as data_core

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
            100
            * raw["points"].sum()
            / (
                2 * (raw["field_goals_attempted"].sum() + 0.44 * raw["free_throws_attempted"].sum())
            ),
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
    assert finances.team_finances_available() is False


def test_team_payroll_history_filters_by_team(warehouse_with_finances_mart):
    df = finances.team_payroll_history(franchise="BOS")
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
    df = finances.team_payroll_history(franchise="GSW")
    assert set(df["team_abbreviation"]) == {"GOS", "GSW"}, (
        "GSW must return both of this franchise's abbreviations"
    )
    # One continuous series, oldest first - the chart plots it in this order.
    assert df["season"].tolist() == sorted(df["season"].tolist())
    assert df["season"].tolist() == ["1995-96", "1996-97"]


def test_team_payroll_history_does_not_merge_an_unrelated_team(warehouse_with_finances_mart):
    """Folding eras into a franchise must not pull in another team's rows."""
    for code in ("BOS", "NYK", "MIA", "DEN"):
        df = finances.team_payroll_history(franchise=code)
        assert set(df["team_abbreviation"]) == {code}, code


def test_salary_cap_history_has_no_apron_before_2023_24(warehouse_with_finances_mart):
    df = finances.salary_cap_history()
    pre_apron = df[df["season"] < "2023-24"]
    assert pre_apron["first_apron"].isna().all()


def test_team_contracts(warehouse_with_finances_mart):
    assert finances.team_contracts_available() is True
    df = finances.team_contracts("2023-24", "BOS")
    assert df["salary_rank"].tolist() == [1, 2, 3]
    assert df["player"].iloc[0] == "Player One"


def test_team_contracts_unavailable_on_an_old_warehouse(legacy_finances_warehouse):
    assert finances.team_contracts_available() is False


def test_a_traded_player_is_split_across_both_rosters(con):
    """Each team's roster counts only the games a player played for it, and
    the stints add back up to his whole season."""
    # The newest season with a trade: early in a season nobody has moved yet.
    for season in seasons.seasons():
        whole = players.player_season_stats(season)
        traded = whole[whole["team_label"].str.count(" → ") == 1]
        if not traded.empty:
            break
    else:
        pytest.skip("no two-team player in any season of this warehouse")
    pick = traded.iloc[0]
    first, second = pick["team_label"].split(" → ")
    stints = []
    for team in (first, second):
        roster = players.team_roster(season, team)
        row = roster[roster["player_id"] == pick["player_id"]]
        assert len(row) == 1, f"{pick['team_label']}: missing from {team}'s roster"
        assert row["team"].iloc[0] == team
        assert row["team_label"].iloc[0] == pick["team_label"]
        stints.append(int(row["gp"].iloc[0]))
    assert sum(stints) == int(pick["gp"])


# --- The data layer against the dashboard's old queries --------------------------
#
# Until Task 12 the Players, Teams, Overview and Arcade pages ran their own
# queries over the game logs (dashboard/lib/db.py). They now read the dbt
# player marts through dashboard/lib/data, renamed to the same short column
# names. The old queries are kept below, verbatim, as the reference: each
# test runs one on the same rows as its replacement and compares the frames
# the page receives - exact equality on the rounded values, true shooting's
# nulls included - for every season in the warehouse.
#
# One deliberate difference: the source logs a few players in two games, for
# two teams, on one date (88 player-dates, all but one before 1985-86).
# There the old max_by(..., game_date) and its string_agg order pick either
# team arbitrarily; the marts break the tie on team code so the answer can't
# change between builds. Those rows are checked against that rule instead.
#
# And one correction: the marts' FG%, 3P% and FT% count only games that
# record both the makes and the attempts. Early seasons often have one
# without the other, and the old sum(made) / sum(attempted) then divided
# over different games (1980-81 seasons at 1080% from the field). Where a
# group has such a game, the new value must instead equal a reference query
# written here, independently of the dbt macro; everywhere else it must
# equal the old one.

# The season line as the old player queries computed it, once per grouping.
# player_season_stats(), and team_roster() with "and team_abbreviation = ?".
_OLD_PLAYER_SEASON_SQL = """
    select
        player_id,
        any_value(player_name)                as player,
        max_by(team_abbreviation, game_date)  as team,
        count(*)                              as gp,
        round(avg(minutes_played), 1)         as mpg,
        round(avg(points), 1)                 as ppg,
        round(avg(total_rebounds), 1)         as rpg,
        round(avg(assists), 1)                as apg,
        round(avg(steals), 1)                 as spg,
        round(avg(blocks), 1)                 as bpg,
        round(avg(three_pointers_made), 1)    as tpg,
        round(avg(field_goals_attempted), 1)  as fga_pg,
        round(avg(three_pointers_attempted), 1) as tpa_pg,
        round(avg(free_throws_attempted), 1)  as fta_pg,
        cast(sum(field_goals_attempted) as int)     as fga_total,
        cast(sum(three_pointers_attempted) as int)  as tpa_total,
        cast(sum(free_throws_attempted) as int)     as fta_total,
        round(sum(field_goals_made) / nullif(sum(field_goals_attempted), 0) * 100, 1)       as fg_pct,
        round(sum(three_pointers_made) / nullif(sum(three_pointers_attempted), 0) * 100, 1) as fg3_pct,
        round(sum(free_throws_made) / nullif(sum(free_throws_attempted), 0) * 100, 1)       as ft_pct,
        case when count(*) filter (
                 where field_goals_attempted is null
                    or free_throws_attempted is null
                    or points is null) > 0
             then null
             else round(sum(points) / nullif(2 * (sum(field_goals_attempted)
                  + 0.44 * sum(free_throws_attempted)), 0) * 100, 1)
        end                                   as ts_pct,
        round(sum(assists) / nullif(sum(turnovers), 0), 2) as ast_to,
        round(avg(plus_minus), 1)             as plus_minus
    from main_staging.stg_player_game_logs
    where season = ?
    group by player_id
    having count(*) >= ?
"""

# The same line for every team in a season at once, so a season is one
# query rather than one per team (about 1,300 in all).
_OLD_ALL_ROSTERS_SQL = """
    select
        player_id,
        team_abbreviation,
        any_value(player_name)                as player,
        max_by(team_abbreviation, game_date)  as team,
        count(*)                              as gp,
        round(avg(minutes_played), 1)         as mpg,
        round(avg(points), 1)                 as ppg,
        round(avg(total_rebounds), 1)         as rpg,
        round(avg(assists), 1)                as apg,
        round(avg(steals), 1)                 as spg,
        round(avg(blocks), 1)                 as bpg,
        round(avg(three_pointers_made), 1)    as tpg,
        round(avg(field_goals_attempted), 1)  as fga_pg,
        round(avg(three_pointers_attempted), 1) as tpa_pg,
        round(avg(free_throws_attempted), 1)  as fta_pg,
        cast(sum(field_goals_attempted) as int)     as fga_total,
        cast(sum(three_pointers_attempted) as int)  as tpa_total,
        cast(sum(free_throws_attempted) as int)     as fta_total,
        round(sum(field_goals_made) / nullif(sum(field_goals_attempted), 0) * 100, 1)       as fg_pct,
        round(sum(three_pointers_made) / nullif(sum(three_pointers_attempted), 0) * 100, 1) as fg3_pct,
        round(sum(free_throws_made) / nullif(sum(free_throws_attempted), 0) * 100, 1)       as ft_pct,
        case when count(*) filter (
                 where field_goals_attempted is null
                    or free_throws_attempted is null
                    or points is null) > 0
             then null
             else round(sum(points) / nullif(2 * (sum(field_goals_attempted)
                  + 0.44 * sum(free_throws_attempted)), 0) * 100, 1)
        end                                   as ts_pct,
        round(sum(assists) / nullif(sum(turnovers), 0), 2) as ast_to,
        round(avg(plus_minus), 1)             as plus_minus
    from main_staging.stg_player_game_logs
    where season = ?
    group by player_id, team_abbreviation
"""

# player_team_paths(): what with_team_labels() merged on as team_label.
_OLD_TEAM_PATHS_SQL = """
    select player_id,
           string_agg(team_abbreviation, ' → ' order by first_game) as team_path,
           count(*)                                                 as n_teams
    from (
        select player_id, team_abbreviation, min(game_date) as first_game
        from main_staging.stg_player_game_logs
        where season = ?
        group by player_id, team_abbreviation
    )
    group by player_id
"""

_OLD_PLAYER_CAREER_SQL = """
    select
        player_id,
        any_value(player_name)                as player,
        max_by(team_abbreviation, game_date)  as team,
        count(distinct season)                as seasons,
        min(season)                           as first_season,
        max(season)                           as last_season,
        count(*)                              as gp,
        cast(max(points) as int)              as career_high,
        cast(sum(points) as int)              as pts_total,
        cast(sum(case when is_win then 1 else 0 end) as int) as wins,
        round(avg(minutes_played), 1)         as mpg,
        round(avg(points), 1)                 as ppg,
        round(avg(total_rebounds), 1)         as rpg,
        round(avg(assists), 1)                as apg,
        round(avg(steals), 1)                 as spg,
        round(avg(blocks), 1)                 as bpg,
        round(avg(three_pointers_made), 1)    as tpg,
        round(avg(field_goals_attempted), 1)  as fga_pg,
        round(avg(three_pointers_attempted), 1) as tpa_pg,
        round(avg(free_throws_attempted), 1)  as fta_pg,
        cast(sum(field_goals_attempted) as int)     as fga_total,
        cast(sum(three_pointers_attempted) as int)  as tpa_total,
        cast(sum(free_throws_attempted) as int)     as fta_total,
        round(sum(field_goals_made) / nullif(sum(field_goals_attempted), 0) * 100, 1)       as fg_pct,
        round(sum(three_pointers_made) / nullif(sum(three_pointers_attempted), 0) * 100, 1) as fg3_pct,
        round(sum(free_throws_made) / nullif(sum(free_throws_attempted), 0) * 100, 1)       as ft_pct,
        case when count(*) filter (
                 where field_goals_attempted is null
                    or free_throws_attempted is null
                    or points is null) > 0
             then null
             else round(sum(points) / nullif(2 * (sum(field_goals_attempted)
                  + 0.44 * sum(free_throws_attempted)), 0) * 100, 1)
        end                                   as ts_pct,
        round(avg(plus_minus), 1)             as plus_minus
    from main_staging.stg_player_game_logs
    group by player_id
    having count(*) >= ?
"""

_OLD_SEASON_BREAKDOWN_SQL = """
    select
        season,
        max_by(team_abbreviation, game_date) as team,
        count(*)                             as gp,
        round(avg(points), 1)                as ppg,
        round(avg(total_rebounds), 1)        as rpg,
        round(avg(assists), 1)               as apg,
        round(avg(three_pointers_made), 1)   as tpg,
        case when count(*) filter (
                 where field_goals_attempted is null
                    or free_throws_attempted is null
                    or points is null) > 0
             then null
             else round(sum(points) / nullif(2 * (sum(field_goals_attempted)
                  + 0.44 * sum(free_throws_attempted)), 0) * 100, 1)
        end                                   as ts_pct,
        sum(field_goals_attempted) + 0.44 * sum(free_throws_attempted)
                                             as shot_poss
    from main_staging.stg_player_game_logs
    where player_id = ?
    group by season
    order by season
"""

_OLD_LEAGUE_SHOOTING_SQL = """
    select
        round(sum(field_goals_made) / sum(field_goals_attempted) * 100, 1)       as fg_pct,
        round(sum(three_pointers_made) / nullif(sum(three_pointers_attempted), 0) * 100, 1) as fg3_pct,
        round(sum(free_throws_made) / sum(free_throws_attempted) * 100, 1)       as ft_pct
    from main_staging.stg_player_game_logs
    where season = ?
"""

# player_latest_seasons() picked each matching player's latest season this
# way (then ran the season line above for it).
_OLD_LATEST_SQL = """
    select player_id, max(season) as season
    from main_marts.mart_player_season
    where contains(strip_accents(lower(player_name)), ?)
      and games_played >= ?
    group by player_id
"""

# arcade_pool(): the pool, with each player-season's age attached.
_OLD_ARCADE_POOL_SQL = """
    select p.*,
           cast(floor(coalesce(adv.age, anchor.age0
                + (cast(left(p.season, 4) as int) - anchor.y0))) as int) as age
    from (
        select
            season,
            player_id,
            any_value(player_name)               as player,
            max_by(team_abbreviation, game_date) as team,
            count(*)                             as gp,
            round(avg(points), 1)                as ppg,
            round(avg(total_rebounds), 1)        as rpg,
            round(avg(assists), 1)               as apg,
            round(avg(steals), 1)                as spg,
            round(avg(blocks), 1)                as bpg,
            round(avg(three_pointers_made), 1)   as tpg,
            round(avg(three_pointers_attempted), 1) as tpa_pg,
            round(sum(field_goals_made) / nullif(sum(field_goals_attempted), 0) * 100, 1)       as fg_pct,
            round(sum(three_pointers_made) / nullif(sum(three_pointers_attempted), 0) * 100, 1) as fg3_pct,
            round(sum(free_throws_made) / nullif(sum(free_throws_attempted), 0) * 100, 1)       as ft_pct
        from main_staging.stg_player_game_logs
        group by season, player_id
        having count(*) >= ? and avg(points) >= ?
    ) p
    left join (
        select player_id, season, age
        from main_staging.stg_player_advanced where age is not null
    ) adv using (player_id, season)
    left join (
        select player_id,
               arg_min(age, season)               as age0,
               min(cast(left(season, 4) as int))  as y0
        from main_staging.stg_player_advanced where age is not null
        group by player_id
    ) anchor using (player_id)
"""

# The old and new names of the season line, for the checks that read a mart
# directly rather than through a data function.
_LINE = {
    "player": "player_name",
    "gp": "games_played",
    "mpg": "minutes_per_game",
    "ppg": "points_per_game",
    "rpg": "rebounds_per_game",
    "apg": "assists_per_game",
    "spg": "steals_per_game",
    "bpg": "blocks_per_game",
    "tpg": "threes_made_per_game",
    "fga_pg": "fga_per_game",
    "tpa_pg": "three_pa_per_game",
    "fta_pg": "fta_per_game",
    "fga_total": "fga_total",
    "tpa_total": "tpa_total",
    "fta_total": "fta_total",
    "fg_pct": "fg_pct",
    "fg3_pct": "fg3_pct",
    "ft_pct": "ft_pct",
    "ts_pct": "true_shooting_pct",
    "plus_minus": "plus_minus_per_game",
    "ast_to": "assist_to_turnover",
}

_SNAPSHOT_TABLES = [
    "main_staging.stg_player_game_logs",
    "main_staging.stg_player_advanced",
    "main_marts.mart_player_season",
    "main_marts.mart_player_team_season",
    "main_marts.mart_player_career",
    "main_marts.mart_league_shooting",
]


@pytest.fixture(scope="module")
def player_snapshot(con, tmp_path_factory):
    """The tables the old and new player queries read, copied into a scratch
    warehouse with the staging views materialized, and the dashboard pointed
    at it. Against the views each old query re-runs the game-log dedup over
    every season (about 0.7 s a query), and this module runs hundreds."""
    path = tmp_path_factory.mktemp("player_marts") / "snapshot.duckdb"
    with duckdb.connect(str(path)) as out:
        out.execute("create schema main_staging")
        out.execute("create schema main_marts")
        for table in _SNAPSHOT_TABLES:
            # Arrow keeps the column types exactly, so the sums and roundings
            # below run on the same integers as in the warehouse.
            out.register("rows", con.execute(f"select * from {table}").to_arrow_table())
            out.execute(f"create table {table} as select * from rows")
            out.unregister("rows")
    with data_core.use_warehouse(path):
        snap = duckdb.connect(str(path), read_only=True)
        yield snap
        snap.close()


def _old(snap, sql, *params):
    """An old query's frame, run on the snapshot the way the old db.py ran it."""
    return snap.execute(sql, list(params)).df()


def _same(columns):
    return {c: c for c in columns}


def _assert_same_rows(old, new, keys, columns, label):
    """old (renamed through `columns`) and new hold the same keys and,
    column by column, exactly the same values - a null only where the other
    side has one."""
    old = old.rename(columns=columns)
    cols = keys + [c for c in columns.values() if c not in keys]
    old = old[cols].sort_values(keys).reset_index(drop=True)
    new = new[cols].sort_values(keys).reset_index(drop=True)
    old_keys = set(old[keys].itertuples(index=False, name=None))
    new_keys = set(new[keys].itertuples(index=False, name=None))
    assert old_keys == new_keys, (
        f"{label}: only in the old query {sorted(old_keys - new_keys)[:5]}, "
        f"only in the new {sorted(new_keys - old_keys)[:5]}"
    )
    pd.testing.assert_frame_equal(old, new, check_dtype=False, check_exact=True, obj=label)


def _tied_last_team(snap, group_by):
    """{key: the tied team codes} for every group whose last game date has
    games for two teams - the rows where the old last team is arbitrary and
    the marts' is the later code."""
    cols = ", ".join(group_by)
    rows = snap.execute(
        f"""
        with last as (
            select {cols}, max(game_date) as game_date
            from main_staging.stg_player_game_logs group by {cols}
        )
        select {cols}, list(distinct team_abbreviation)
        from main_staging.stg_player_game_logs join last using ({cols}, game_date)
        group by {cols}
        having count(distinct team_abbreviation) > 1
        """
    ).fetchall()
    return {row[:-1]: row[-1] for row in rows}


def _apply_tie_break(old, ties, keys):
    """The old frame with the marts' tie-break (the later team code) applied
    to its team column, after checking its arbitrary pick was one of the
    tied teams."""
    old = old.copy()
    for i, row in old.iterrows():
        tied = ties.get(tuple(row[k] for k in keys))
        if tied:
            assert row["team"] in tied, (row[keys].tolist(), row["team"], tied)
            old.at[i, "team"] = max(tied)
    return old


_PCT_PAIRS = {
    "fg_pct": ("field_goals_made", "field_goals_attempted"),
    "fg3_pct": ("three_pointers_made", "three_pointers_attempted"),
    "ft_pct": ("free_throws_made", "free_throws_attempted"),
}


def _corrected_pcts(snap, group_by):
    """Per group: for each percentage, whether any game is missing the makes
    or the attempts (`<pct>_gappy`, the groups the marts correct) and the
    corrected value, computed only over games that record both."""
    exprs = []
    for pct, (made, att) in _PCT_PAIRS.items():
        both = f"filter (where {made} is not null and {att} is not null)"
        exprs.append(f"bool_or({made} is null or {att} is null) as {pct}_gappy")
        exprs.append(f"round(sum({made}) {both} / nullif(sum({att}) {both}, 0) * 100, 1) as {pct}")
    cols = ", ".join(group_by)
    return snap.execute(
        f"select {cols}, {', '.join(exprs)} from main_staging.stg_player_game_logs group by {cols}"
    ).df()


def _adopt_corrected_pcts(old, corrected, keys):
    """The old frame with its percentages replaced by the corrected reference
    values in the gappy groups, after checking each of those is a real
    percentage (or null). The new frame is then compared to this one, so it
    must match the reference there and the old query everywhere else."""
    pcts = list(_PCT_PAIRS)
    old = old.reset_index(drop=True)
    ref = old[keys].merge(corrected, on=keys, how="left")
    for col in pcts:
        mask = ref[f"{col}_gappy"].fillna(False).astype(bool).to_numpy()
        new = ref.loc[mask, col]
        bad = new[(new < 0) | (new > 100)]
        assert bad.empty, (col, ref.loc[bad.index, keys].to_dict("records")[:5], bad.tolist()[:5])
        old.loc[mask, col] = new.to_numpy()
    return old


def _seasons(snap):
    return [
        r[0]
        for r in snap.execute(
            "select distinct season from main_staging.stg_player_game_logs order by 1"
        ).fetchall()
    ]


def _old_season_line(snap, season, ties, corrected):
    """The old player_season_stats(season) frame, with the tie-break and the
    percentage correction applied."""
    old = _old(snap, _OLD_PLAYER_SEASON_SQL, season, 1).assign(season=season)
    old = _apply_tie_break(old, ties, ["season", "player_id"])
    return _adopt_corrected_pcts(old, corrected, ["season", "player_id"])


def test_player_season_stats_match_the_old_query(player_snapshot):
    """players.player_season_stats() against the query it replaced, every
    season, every column the old one returned."""
    snap = player_snapshot
    keys = ["season", "player_id"]
    ties = _tied_last_team(snap, keys)
    corrected = _corrected_pcts(snap, keys)
    seasons_seen = _seasons(snap)
    assert seasons_seen
    for season in seasons_seen:
        old = _old_season_line(snap, season, ties, corrected)
        new = players.player_season_stats(season).assign(season=season)
        columns = _same(c for c in old.columns if c not in keys)
        _assert_same_rows(old, new, keys, columns, f"player_season_stats {season}")
    # The mart's pre-existing names carry the same values as the new ones.
    mart = snap.execute("select * from main_marts.mart_player_season").df()
    assert (mart["team_abbreviation"] == mart["team"]).all()
    assert mart["plus_minus"].equals(mart["plus_minus_per_game"])


def test_min_games_filters_like_the_old_having(player_snapshot):
    season = _seasons(player_snapshot)[-1]
    old = _old(player_snapshot, _OLD_PLAYER_SEASON_SQL, season, 25)
    new = players.player_season_stats(season, 25)
    assert sorted(old["player_id"]) == sorted(new["player_id"])


def test_team_label_matches_the_old_team_paths(player_snapshot):
    """team_label (player_season_stats, team_roster) against the old
    player_team_paths(), every season. Where two stints start on the same
    date the old order is arbitrary; there the teams must still be the same
    ones."""
    snap = player_snapshot
    tied = set(
        snap.execute(
            """
            select distinct season, player_id from main_marts.mart_player_team_season
            group by season, player_id, first_game having count(*) > 1
            """
        ).fetchall()
    )
    traded = 0
    for season in _seasons(snap):
        old = _old(snap, _OLD_TEAM_PATHS_SQL, season).assign(season=season)
        new = players.player_season_stats(season)[["player_id", "team_label"]].assign(season=season)
        got = new.merge(old, on=["season", "player_id"], how="outer")
        assert got["team_label"].notna().all() and got["team_path"].notna().all(), season
        for row in got.itertuples(index=False):
            if (row.season, row.player_id) in tied:
                assert sorted(row.team_label.split(" → ")) == sorted(row.team_path.split(" → "))
            else:
                assert row.team_label == row.team_path, (season, row.player_id)
        traded += int((got["n_teams"] > 1).sum())
    assert traded > 0, "expected at least one traded player to compare"


def test_team_rosters_match_the_old_query(player_snapshot):
    """mart_player_team_season against the old roster query for every team
    in every season - each stint's own games only - and team_roster() itself
    for every team in the latest season, with each player's whole-season
    team_label."""
    snap = player_snapshot
    mart = snap.execute("select * from main_marts.mart_player_team_season").df()
    keys = ["season", "team_abbreviation", "player_id"]
    corrected = _corrected_pcts(snap, keys)
    all_seasons = _seasons(snap)
    for season in all_seasons:
        old = _old(snap, _OLD_ALL_ROSTERS_SQL, season).assign(season=season)
        old = _adopt_corrected_pcts(old, corrected, keys)
        _assert_same_rows(
            old, mart[mart["season"] == season], keys, _LINE, f"mart_player_team_season {season}"
        )
    latest = all_seasons[-1]
    old_all = _old(snap, _OLD_ALL_ROSTERS_SQL, latest).assign(season=latest)
    old_all = _adopt_corrected_pcts(old_all, corrected, keys)
    labels = players.player_season_stats(latest).set_index("player_id")["team_label"]
    for team in sorted(old_all["team_abbreviation"].unique()):
        new = players.team_roster(latest, team).assign(season=latest, team_abbreviation=team)
        old = old_all[old_all["team_abbreviation"] == team]
        columns = _same(c for c in old.columns if c not in keys)
        _assert_same_rows(old, new, keys, columns, f"team_roster {latest} {team}")
        assert (new["team_label"].to_numpy() == labels.loc[new["player_id"]].to_numpy()).all()


def test_player_career_stats_match_the_old_query(player_snapshot):
    """players.player_career_stats() against the query it replaced. The old
    one took any spelling of a renamed player's name; the mart takes the
    latest, so that is applied to the old frame first."""
    snap = player_snapshot
    old = _old(snap, _OLD_PLAYER_CAREER_SQL, 1)
    old = _apply_tie_break(old, _tied_last_team(snap, ["player_id"]), ["player_id"])
    renamed = {
        r[0]
        for r in snap.execute(
            """
            select player_id from main_staging.stg_player_game_logs
            group by player_id having count(distinct player_name) > 1
            """
        ).fetchall()
    }
    latest = dict(
        snap.execute(
            """
            select player_id, max_by(player_name, game_date)
            from main_staging.stg_player_game_logs group by player_id
            """
        ).fetchall()
    )
    for pid in renamed:
        old.loc[old["player_id"] == pid, "player"] = latest[pid]
    old = _adopt_corrected_pcts(old, _corrected_pcts(snap, ["player_id"]), ["player_id"])
    new = players.player_career_stats(1)
    assert list(new.columns) == list(old.columns)
    columns = _same(c for c in old.columns if c != "player_id")
    _assert_same_rows(old, new, ["player_id"], columns, "player_career_stats")


def test_player_season_breakdown_matches_the_old_query(player_snapshot):
    """players.player_season_breakdown(), shot_poss included, for the longest
    careers and the longest pre-1985-86 ones (where true shooting's null rule
    bites)."""
    snap = player_snapshot
    sample = [
        r[0]
        for r in snap.execute(
            """
            (select player_id from main_marts.mart_player_career
             order by games_played desc, player_id limit 15)
            union
            (select player_id from main_marts.mart_player_career
             where first_season < '1985-86'
             order by games_played desc, player_id limit 15)
            """
        ).fetchall()
    ]
    assert sample
    keys = ["season", "player_id"]
    ties = _tied_last_team(snap, keys)
    null_ts = 0
    for pid in sample:
        old = _old(snap, _OLD_SEASON_BREAKDOWN_SQL, pid).assign(player_id=pid)
        old = _apply_tie_break(old, ties, keys)
        new = players.player_season_breakdown(pid)
        assert list(new.columns) == [c for c in old.columns if c != "player_id"]
        assert new["season"].is_monotonic_increasing
        null_ts += int(old["ts_pct"].isna().sum())
        columns = _same(c for c in old.columns if c not in keys)
        _assert_same_rows(
            old, new.assign(player_id=pid), keys, columns, f"player_season_breakdown {pid}"
        )
    assert null_ts > 0, "expected the sample to include a season with true shooting withheld"


def test_league_shooting_averages_match_the_old_query(player_snapshot):
    """players.league_shooting_averages() against the query it replaced,
    every season (corrected where a game is missing the makes or the
    attempts)."""
    snap = player_snapshot
    all_seasons = _seasons(snap)
    old = pd.concat(
        [_old(snap, _OLD_LEAGUE_SHOOTING_SQL, s).assign(season=s) for s in all_seasons],
        ignore_index=True,
    )
    old = _adopt_corrected_pcts(old, _corrected_pcts(snap, ["season"]), ["season"])
    new = pd.DataFrame(
        [players.league_shooting_averages(s).to_dict() | {"season": s} for s in all_seasons]
    )
    _assert_same_rows(old, new, ["season"], _same(_PCT_PAIRS), "league_shooting_averages")


def test_league_shooting_of_an_unknown_season_is_all_null(player_snapshot):
    out = players.league_shooting_averages("1900-01")
    assert list(out.index) == list(_PCT_PAIRS) and out.isna().all()


@pytest.mark.parametrize(("needle", "min_games"), [("son", 1), ("jo", 25), ("ic", 1)])
def test_player_latest_seasons_match_the_old_search(player_snapshot, needle, min_games):
    """players.player_latest_seasons() against the old search: the same
    players, each at the same season, with that season's line and
    team_label. The limit is set high so the old query's unordered cut-off
    can't pick a different set."""
    snap = player_snapshot
    picked = _old(snap, _OLD_LATEST_SQL, needle, min_games)
    assert len(picked), f"no player matches {needle!r} in this warehouse"
    new = players.player_latest_seasons(needle, min_games, limit=100_000)
    keys = ["season", "player_id"]
    ties = _tied_last_team(snap, keys)
    corrected = _corrected_pcts(snap, keys)
    old_rows = []
    for season, ids in picked.groupby("season")["player_id"]:
        line = _old_season_line(snap, season, ties, corrected)
        paths = _old(snap, _OLD_TEAM_PATHS_SQL, season)[["player_id", "team_path"]]
        line = line.merge(paths, on="player_id")
        old_rows.append(line[line["player_id"].isin(ids)])
    old = pd.concat(old_rows, ignore_index=True)
    assert sorted(old.columns) == sorted(
        [c for c in new.columns if c != "team_label"] + ["team_path"]
    )
    columns = _same(c for c in old.columns if c not in [*keys, "team_path"])
    _assert_same_rows(old, new, keys, columns, f"player_latest_seasons {needle!r}")
    # team_label as the old team path; a same-date stint tie orders the old
    # one arbitrarily (see above), so compare the teams there.
    labels = new.merge(old, on=keys)
    for row in labels.itertuples(index=False):
        assert sorted(row.team_label.split(" → ")) == sorted(row.team_path.split(" → "))
    order = list(zip(new["season"], new["player_id"], strict=True))
    assert order == sorted(order, key=lambda k: (k[0], -k[1]), reverse=True)


def test_player_latest_seasons_respects_the_limit_and_an_empty_search(player_snapshot):
    assert players.player_latest_seasons("   ").empty
    few = players.player_latest_seasons("a", limit=3)
    assert len(few) == 3
    assert list(few["season"]) == sorted(few["season"], reverse=True)


def test_arcade_pool_matches_the_old_query(player_snapshot):
    """arcade_data.arcade_pool() against the old pool-plus-ages query. The
    one difference is the scoring floor: the new pool filters on the
    rounded points_per_game the cards show, so a season averaging 13.95 to
    13.99 (shown as 14.0) is now in it; nothing else changes."""
    snap = player_snapshot
    keys = ["season", "player_id"]
    old = _old(snap, _OLD_ARCADE_POOL_SQL, 50, 14.0)
    old = _apply_tie_break(old, _tied_last_team(snap, keys), keys)
    old = _adopt_corrected_pcts(old, _corrected_pcts(snap, keys), keys)
    new = arcade_data.arcade_pool()
    assert list(new.columns) == list(old.columns)
    gained = set(
        snap.execute(
            """
            select season, player_id from main_staging.stg_player_game_logs
            group by season, player_id
            having count(*) >= 50 and avg(points) < 14 and round(avg(points), 1) >= 14
            """
        ).fetchall()
    )
    new_keys = set(new[keys].itertuples(index=False, name=None))
    old_keys = set(old[keys].itertuples(index=False, name=None))
    assert new_keys - old_keys == gained and old_keys <= new_keys
    kept = new[[k not in gained for k in new[keys].itertuples(index=False, name=None)]]
    columns = _same(c for c in old.columns if c not in keys)
    _assert_same_rows(old, kept, keys, columns, "arcade_pool")
    assert new["age"].notna().any()


def test_season_mart_age_matches_the_old_age_rule(player_snapshot):
    """mart_player_season.age against the old Arcade age rule, applied to
    every player-season (not only the pool's)."""
    snap = player_snapshot
    old = snap.execute(
        """
        select p.season, p.player_id,
               cast(floor(coalesce(adv.age, anchor.age0
                    + (cast(left(p.season, 4) as int) - anchor.y0))) as int) as age
        from main_marts.mart_player_season p
        left join (
            select player_id, season, age
            from main_staging.stg_player_advanced where age is not null
        ) adv using (player_id, season)
        left join (
            select player_id,
                   arg_min(age, season)               as age0,
                   min(cast(left(season, 4) as int))  as y0
            from main_staging.stg_player_advanced where age is not null
            group by player_id
        ) anchor using (player_id)
        """
    ).df()
    mart = snap.execute("select season, player_id, age from main_marts.mart_player_season").df()
    _assert_same_rows(old, mart, ["season", "player_id"], {"age": "age"}, "mart age")
    assert mart["age"].notna().any()


def test_true_shooting_is_gated_on_its_own_inputs(player_snapshot):
    """The corrected true_shooting_pct is null exactly where a game has a
    null FGA, FTA or points - not wherever box_score_complete is false - so
    pre-1985-86 seasons with complete shot data now get a number."""
    snap = player_snapshot
    wrong = snap.execute(
        """
        with gate as (
            select season, player_id,
                   count(*) filter (where field_goals_attempted is null
                                       or free_throws_attempted is null
                                       or points is null) as null_games,
                   sum(field_goals_attempted) + 0.44 * sum(free_throws_attempted) as attempts
            from main_staging.stg_player_game_logs group by season, player_id
        )
        select m.season, m.player_id, m.true_shooting_pct, g.null_games
        from main_marts.mart_player_season m join gate g using (season, player_id)
        where (m.true_shooting_pct is null) <> (g.null_games > 0 or g.attempts = 0)
        """
    ).fetchall()
    assert not wrong, wrong[:5]
    gained = snap.execute(
        """
        select count(*) from main_marts.mart_player_season
        where not box_score_complete and true_shooting_pct is not null
        """
    ).fetchone()
    assert gained is not None and gained[0] > 0


def test_the_advanced_page_reads_team_label_from_the_mart(player_snapshot):
    """The Advanced page shows mart_player_season's own team_label (it used
    to merge one on). Every row needs one, and it must be the label the
    Players page shows."""
    season = _seasons(player_snapshot)[-1]
    stats = advanced.player_advanced(season)
    assert len(stats) and stats["team_label"].notna().all()
    labels = players.player_season_stats(season).set_index("player_id")["team_label"]
    assert (stats["team_label"].to_numpy() == labels.loc[stats["player_id"]].to_numpy()).all()
