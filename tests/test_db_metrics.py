"""Regression tests for the SQL in dashboard/lib/db.py.

The app computes some rate stats independently of the dbt marts so the
dashboard still works when the marts are absent. That independence is
deliberate, but it lets the two implementations drift - these tests pin
them together.
"""

import duckdb
import pandas as pd
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
    assert db.team_finances_available() is False


def test_team_payroll_history_filters_by_team(warehouse_with_finances_mart):
    df = db.team_payroll_history(franchise="BOS")
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
    df = db.team_payroll_history(franchise="GSW")
    assert set(df["team_abbreviation"]) == {"GOS", "GSW"}, (
        "GSW must return both of this franchise's abbreviations"
    )
    # One continuous series, oldest first - the chart plots it in this order.
    assert df["season"].tolist() == sorted(df["season"].tolist())
    assert df["season"].tolist() == ["1995-96", "1996-97"]


def test_team_payroll_history_does_not_merge_an_unrelated_team(warehouse_with_finances_mart):
    """Folding eras into a franchise must not pull in another team's rows."""
    for code in ("BOS", "NYK", "MIA", "DEN"):
        df = db.team_payroll_history(franchise=code)
        assert set(df["team_abbreviation"]) == {code}, code


def test_salary_cap_history_has_no_apron_before_2023_24(warehouse_with_finances_mart):
    df = db.salary_cap_history()
    pre_apron = df[df["season"] < "2023-24"]
    assert pre_apron["first_apron"].isna().all()


def test_team_contracts(warehouse_with_finances_mart):
    assert db.team_contracts_available() is True
    df = db.team_contracts("2023-24", "BOS")
    assert df["salary_rank"].tolist() == [1, 2, 3]
    assert df["player"].iloc[0] == "Player One"


def test_team_contracts_unavailable_on_an_old_warehouse(legacy_finances_warehouse):
    assert db.team_contracts_available() is False


def test_a_traded_player_is_split_across_both_rosters(con):
    """Each team's roster counts only the games a player played for it, and
    the stints add back up to his whole season."""
    season = db.latest_season()
    paths = db.player_team_paths(season)
    traded = paths[paths["n_teams"] == 2]
    if traded.empty:
        pytest.skip(f"no two-team player in {season} in this warehouse")
    pick = traded.iloc[0]
    first, second = pick["team_path"].split(" → ")
    whole = db.player_season_stats(season)
    whole_gp = int(whole.loc[whole["player_id"] == pick["player_id"], "gp"].iloc[0])
    stints = []
    for team in (first, second):
        roster = db.team_roster(season, team)
        row = roster[roster["player_id"] == pick["player_id"]]
        assert len(row) == 1, f"{pick['team_path']}: missing from {team}'s roster"
        assert row["team"].iloc[0] == team
        stints.append(int(row["gp"].iloc[0]))
    assert sum(stints) == whole_gp


# --- The player marts against the dashboard's own queries ------------------------
#
# The dbt player marts are to become the single source of player stats: the
# Players and Teams pages will read them instead of the queries in db.py.
# These tests pin the marts to what those queries return today, for every
# season in the warehouse - exact equality on the rounded values, true
# shooting's nulls included - so switching the pages over changes nothing
# on screen.
#
# One deliberate difference: the source logs a few players in two games, for
# two teams, on one date (88 player-dates, all but one before 1985-86).
# There the dashboard's max_by(..., game_date) and its string_agg order
# pick either team arbitrarily; the marts break the tie on team code so the
# answer can't change between builds. Those rows are checked against that
# rule instead.
#
# And one correction: the marts' FG%, 3P% and FT% count only games that
# record both the makes and the attempts. Early seasons often have one
# without the other, and the dashboard's sum(made) / sum(attempted) then
# divides over different games (1980-81 seasons at 1080% from the field).
# Where a group has such a game, the mart's value is checked to be a real
# percentage instead; everywhere else it must equal the dashboard's.

# Dashboard column -> mart column, for the season line all three player
# marts share.
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
}
_SEASON_LINE = {**_LINE, "ast_to": "assist_to_turnover"}
_CAREER_LINE = {
    **_LINE,
    "seasons": "seasons",
    "first_season": "first_season",
    "last_season": "last_season",
    "career_high": "career_high",
    "pts_total": "pts_total",
    "wins": "wins",
}

_SNAPSHOT_TABLES = [
    "main_staging.stg_player_game_logs",
    "main_staging.stg_player_advanced",
    "main_marts.mart_player_season",
    "main_marts.mart_player_team_season",
    "main_marts.mart_player_career",
    "main_marts.mart_league_shooting",
]


def _reset_player_caches() -> None:
    db.q.clear()
    db.player_ages_available.clear()


@pytest.fixture(scope="module")
def player_snapshot(con, tmp_path_factory):
    """The tables the player queries read, copied into a scratch warehouse
    with the staging views materialized, and db pointed at it. The
    dashboard's queries then run verbatim, through db's own functions, on
    the same rows. Against the views each one re-runs the game-log dedup
    over every season (about 0.7 s a query), and this module runs hundreds."""
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
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(db, "DB_PATH", path)
        _reset_player_caches()
        snap = duckdb.connect(str(path), read_only=True)
        yield snap
        snap.close()
    _reset_player_caches()


def _assert_same_rows(dash, mart, keys, columns, label):
    """dash (the dashboard's frame, renamed through `columns`) and mart hold
    the same keys and, column by column, exactly the same values - a null
    only where the other side has one."""
    dash = dash.rename(columns=columns)
    cols = keys + [c for c in columns.values() if c not in keys]
    dash = dash[cols].sort_values(keys).reset_index(drop=True)
    mart = mart[cols].sort_values(keys).reset_index(drop=True)
    dash_keys = set(dash[keys].itertuples(index=False, name=None))
    mart_keys = set(mart[keys].itertuples(index=False, name=None))
    assert dash_keys == mart_keys, (
        f"{label}: only in the dashboard {sorted(dash_keys - mart_keys)[:5]}, "
        f"only in the mart {sorted(mart_keys - dash_keys)[:5]}"
    )
    pd.testing.assert_frame_equal(dash, mart, check_dtype=False, check_exact=True, obj=label)


def _tied_last_team(snap, group_by):
    """{key: the tied team codes} for every group whose last game date has
    games for two teams - the rows where the dashboard's last team is
    arbitrary and the marts' is the later code."""
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


def _apply_tie_break(dash, ties, keys):
    """The dashboard's frame with the marts' tie-break (the later team code)
    applied to its team column, after checking its arbitrary pick was one
    of the tied teams."""
    dash = dash.copy()
    for i, row in dash.iterrows():
        tied = ties.get(tuple(row[k] for k in keys))
        if tied:
            assert row["team"] in tied, (row[keys].tolist(), row["team"], tied)
            dash.at[i, "team"] = max(tied)
    return dash


_PCT_PAIRS = {
    "fg_pct": ("field_goals_made", "field_goals_attempted"),
    "fg3_pct": ("three_pointers_made", "three_pointers_attempted"),
    "ft_pct": ("free_throws_made", "free_throws_attempted"),
}


def _gappy_pcts(snap, group_by):
    """Per group, whether any game is missing the makes or the attempts for
    each percentage - the groups where the marts' percentage is corrected."""
    flags = ", ".join(
        f"bool_or({made} is null or {att} is null) as {pct}"
        for pct, (made, att) in _PCT_PAIRS.items()
    )
    cols = ", ".join(group_by)
    return snap.execute(
        f"select {cols}, {flags} from main_staging.stg_player_game_logs group by {cols}"
    ).df()


def _adopt_corrected_pcts(dash, mart, gappy, keys):
    """The dashboard's frame with its percentages replaced by the mart's in
    the gappy groups, after checking each of those is a real percentage (or
    null). Returns the frame and the number of values replaced."""
    pcts = list(_PCT_PAIRS)
    dash = dash.reset_index(drop=True)
    flags = dash[keys].merge(gappy, on=keys, how="left")
    fixed = dash[keys].merge(mart[keys + pcts], on=keys, how="left")
    replaced = 0
    for col in pcts:
        mask = flags[col].fillna(False).astype(bool).to_numpy()
        new = fixed.loc[mask, col]
        bad = new[(new < 0) | (new > 100)]
        assert bad.empty, (col, fixed.loc[bad.index, keys].to_dict("records")[:5], bad.tolist()[:5])
        dash.loc[mask, col] = new.to_numpy()
        replaced += int(mask.sum())
    return dash, replaced


def _seasons(snap):
    return [
        r[0]
        for r in snap.execute(
            "select distinct season from main_staging.stg_player_game_logs order by 1"
        ).fetchall()
    ]


def test_season_mart_matches_the_players_page(player_snapshot):
    """mart_player_season against player_season_stats(), every season."""
    snap = player_snapshot
    keys = ["season", "player_id"]
    ties = _tied_last_team(snap, keys)
    gappy = _gappy_pcts(snap, keys)
    mart = snap.execute("select * from main_marts.mart_player_season").df()
    seasons = _seasons(snap)
    assert seasons
    for season in seasons:
        dash = db.player_season_stats(season).assign(season=season)
        dash = _apply_tie_break(dash, ties, keys)
        dash, _ = _adopt_corrected_pcts(dash, mart, gappy, keys)
        _assert_same_rows(
            dash,
            mart[mart["season"] == season],
            ["season", "player_id"],
            {**_SEASON_LINE, "team": "team"},
            f"mart_player_season {season}",
        )
    # The pre-existing names carry the same values.
    assert (mart["team_abbreviation"] == mart["team"]).all()
    assert mart["plus_minus"].equals(mart["plus_minus_per_game"])


# team_roster()'s query for every team in a season at once: the same select,
# grouped by team instead of filtered to one, so a season is one query rather
# than one per team (about 1,300 in all).
_ALL_ROSTERS_SQL = db._TEAM_ROSTER_SQL.replace(
    "    where season = ? and team_abbreviation = ?\n    group by player_id\n",
    "    where season = ?\n    group by player_id, team_abbreviation\n",
)
assert _ALL_ROSTERS_SQL != db._TEAM_ROSTER_SQL


def test_team_season_mart_matches_every_team_roster(player_snapshot):
    """mart_player_team_season against team_roster()'s query for every team
    in every season - each stint's own games only - and against
    team_roster() itself for every team in the latest season."""
    snap = player_snapshot
    mart = snap.execute("select * from main_marts.mart_player_team_season").df()
    keys = ["season", "team_abbreviation", "player_id"]
    gappy = _gappy_pcts(snap, keys)
    seasons = _seasons(snap)
    for season in seasons:
        dash = db.q(_ALL_ROSTERS_SQL, (season, 1)).assign(season=season)
        dash["team_abbreviation"] = dash["team"]
        dash, _ = _adopt_corrected_pcts(dash, mart, gappy, keys)
        _assert_same_rows(
            dash,
            mart[mart["season"] == season],
            keys,
            _SEASON_LINE,
            f"mart_player_team_season {season}",
        )
    latest = mart[mart["season"] == seasons[-1]]
    for team in sorted(latest["team_abbreviation"].unique()):
        dash = db.team_roster(seasons[-1], team).assign(season=seasons[-1], team_abbreviation=team)
        dash, _ = _adopt_corrected_pcts(dash, mart, gappy, keys)
        _assert_same_rows(
            dash,
            latest[latest["team_abbreviation"] == team],
            keys,
            _SEASON_LINE,
            f"team_roster {seasons[-1]} {team}",
        )


def test_team_path_matches_player_team_paths(player_snapshot):
    """mart_player_season.team_label against player_team_paths(), every
    season. Where two stints start on the same date the dashboard's order is
    arbitrary; there the teams must still be the same ones."""
    snap = player_snapshot
    mart = snap.execute(
        "select season, player_id, team_label as team_path from main_marts.mart_player_season"
    ).df()
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
        dash = db.player_team_paths(season).assign(season=season)
        got = mart[mart["season"] == season].merge(
            dash, on=["season", "player_id"], how="outer", suffixes=("_mart", "_dash")
        )
        assert got["team_path_mart"].notna().all() and got["team_path_dash"].notna().all(), season
        for row in got.itertuples(index=False):
            if (row.season, row.player_id) in tied:
                assert sorted(row.team_path_mart.split(" → ")) == sorted(
                    row.team_path_dash.split(" → ")
                )
            else:
                assert row.team_path_mart == row.team_path_dash, (season, row.player_id)
        traded += int((got["n_teams"] > 1).sum())
    assert traded > 0, "expected at least one traded player to compare"


def test_career_mart_matches_player_career_stats(player_snapshot):
    """mart_player_career against player_career_stats(). The dashboard takes
    any spelling of a renamed player's name; the mart takes the latest, so
    names are compared where a player has only ever had one."""
    snap = player_snapshot
    mart = snap.execute("select * from main_marts.mart_player_career").df()
    dash = db.player_career_stats(1)
    ties = _tied_last_team(snap, ["player_id"])
    dash = _apply_tie_break(dash, ties, ["player_id"])
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
        dash.loc[dash["player_id"] == pid, "player"] = latest[pid]
    dash, _ = _adopt_corrected_pcts(dash, mart, _gappy_pcts(snap, ["player_id"]), ["player_id"])
    _assert_same_rows(
        dash, mart, ["player_id"], {**_CAREER_LINE, "team": "team"}, "mart_player_career"
    )


def test_season_mart_matches_the_career_trajectory(player_snapshot):
    """mart_player_season against player_season_breakdown(), including
    shot_poss, for the longest careers and the longest pre-1985-86 ones
    (where true shooting's null rule bites)."""
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
    ties = _tied_last_team(snap, ["season", "player_id"])
    mart = snap.execute("select * from main_marts.mart_player_season").df()
    null_ts = 0
    for pid in sample:
        dash = db.player_season_breakdown(pid).assign(player_id=pid)
        dash = _apply_tie_break(dash, ties, ["season", "player_id"])
        null_ts += int(dash["ts_pct"].isna().sum())
        _assert_same_rows(
            dash,
            mart[mart["player_id"] == pid],
            ["season", "player_id"],
            {
                "team": "team",
                "gp": "games_played",
                "ppg": "points_per_game",
                "rpg": "rebounds_per_game",
                "apg": "assists_per_game",
                "tpg": "threes_made_per_game",
                "ts_pct": "true_shooting_pct",
                "shot_poss": "shot_poss",
            },
            f"player_season_breakdown {pid}",
        )
    assert null_ts > 0, "expected the sample to include a season with true shooting withheld"


def test_league_shooting_mart_matches_league_shooting_averages(player_snapshot):
    """mart_league_shooting against league_shooting_averages(), every season
    (corrected where a game is missing the makes or the attempts)."""
    snap = player_snapshot
    mart = snap.execute("select * from main_marts.mart_league_shooting").df()
    seasons = _seasons(snap)
    assert sorted(mart["season"]) == seasons
    dash = pd.DataFrame(
        [db.league_shooting_averages(season).to_dict() | {"season": season} for season in seasons]
    )
    dash, _ = _adopt_corrected_pcts(dash, mart, _gappy_pcts(snap, ["season"]), ["season"])
    _assert_same_rows(dash, mart, ["season"], {c: c for c in _PCT_PAIRS}, "mart_league_shooting")


def test_season_mart_age_matches_the_arcade(player_snapshot):
    """mart_player_season.age against the Arcade's age query, applied to
    every player-season."""
    snap = player_snapshot
    assert db.player_ages_available()
    pool = "select season, player_id from main_marts.mart_player_season"
    dash = db.q(db._ARCADE_AGES_SQL.format(pool=pool))
    mart = snap.execute("select season, player_id, age from main_marts.mart_player_season").df()
    _assert_same_rows(dash, mart, ["season", "player_id"], {"age": "age"}, "mart_player_season age")
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


def test_the_advanced_page_can_still_label_the_season_mart(player_snapshot):
    """The Advanced page reads mart_player_season with select * and passes it
    through with_team_labels(), which merges in player_team_paths(). A mart
    column sharing a name with that merge (team_path, say) splits it into
    team_path_x/_y and takes the page down - on the deployed app too, which
    reads whatever warehouse the refresh publishes."""
    season = _seasons(player_snapshot)[-1]
    stats = db.player_advanced(season)
    merged_in = db.player_team_paths(season).columns
    assert set(stats.columns) & set(merged_in) == {"player_id"}
    labelled = db.with_team_labels(stats, season, team_col="team_abbreviation")
    assert len(labelled) == len(stats) and labelled["team_label"].notna().all()
