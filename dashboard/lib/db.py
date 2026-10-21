"""Read-only data access for the dashboard. All queries hit the DuckDB
warehouse's staging views and are cached by Streamlit. Explore pages are
season-scoped; the Arcade pulls from every ingested season."""

from __future__ import annotations

import unicodedata
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import streamlit as st

from . import franchises

DB_PATH = Path(__file__).resolve().parents[2] / "warehouse" / "basketball.duckdb"

# nba_api's static team data has no conference field, so map it here.
# Covers current franchises plus historical/relocated abbreviations.
#
# dbt's mart_team_standings is the source of truth for the mapping and
# carries the same two lists; these must stay in step with it. They are
# kept here because conference() has a live caller that never touches the
# mart - views/arcade.py builds its clue text from it - and because
# standings() needs the mapping in its no-mart fallback path.
#
# PHL, GOS and SAN are the modern PHI/GSW/SAS franchises under the
# abbreviations the source data uses for 1979-80 through 1995-96. They
# were missing from both lists, and because conference() defaulted
# anything unlisted to West, a 1980s 76er was reported as a Western
# Conference player for 17 seasons of data. Anything added here must be
# added to mart_team_standings.sql too, where
# assert_standings_conference_is_assigned now fails the build on an
# unlisted abbreviation.
EAST = {
    "ATL",
    "BOS",
    "BKN",
    "NJN",
    "CHA",
    "CHH",
    "CHI",
    "CLE",
    "DET",
    "IND",
    "MIA",
    "MIL",
    "NYK",
    "ORL",
    "PHI",
    "PHL",
    "TOR",
    "WAS",
    "WSB",
}
WEST = {
    "DAL",
    "DEN",
    "GSW",
    "GOS",
    "HOU",
    "LAC",
    "SDC",
    "LAL",
    "MEM",
    "VAN",
    "MIN",
    "NOP",
    "NOH",
    "NOK",
    "OKC",
    "SEA",
    "PHX",
    "POR",
    "SAC",
    "KCK",
    "SAS",
    "SAN",
    "UTA",
    "UTH",
}


def conference(team_abbr: str) -> str:
    return "East" if team_abbr in EAST else "West"


def warehouse_exists() -> bool:
    return DB_PATH.exists()


@st.cache_data(ttl=600, show_spinner=False)
def q(sql: str, params: tuple = ()) -> pd.DataFrame:
    """Run a read-only query and return a DataFrame (cached on sql+params)."""
    with duckdb.connect(str(DB_PATH), read_only=True) as con:
        return con.execute(sql, list(params)).df()


# --- Seasons ------------------------------------------------------------------


def seasons() -> list[str]:
    """All ingested seasons, newest first."""
    return q("select distinct season from main_staging.stg_team_game_logs order by 1 desc")[
        "season"
    ].tolist()


def latest_season() -> str:
    return seasons()[0]


# --- Player stats -------------------------------------------------------------

# TS% is withheld for a player-season only when that player's own games
# include a null field_goals_attempted, free_throws_attempted or points.
# sum() skips nulls, so without this guard one such game counts its
# points in the numerator while contributing nothing to the denominator -
# confirmed on Jim Brewer's 1979-80 season, where 8 of 75 games have a
# null field_goals_attempted and the unguarded query reports a 78.1% true
# shooting season. This is deliberately narrower than mart_player_season's
# box_score_complete flag, which also nulls a season for missing
# TEAM-level columns (needed by usage%, rebound rate, etc.) that true
# shooting does not depend on - checked directly, only 92 of 230
# qualifying 1979-80 players actually have a null in these three columns;
# the other 138 have complete shot data and a real number is correct.
_PLAYER_SEASON_SQL = """
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


def player_season_stats(season: str, min_games: int = 1) -> pd.DataFrame:
    return q(_PLAYER_SEASON_SQL, (season, min_games))


# The same per-player season line, counting only games played for one team.
# A player traded mid-season appears on both teams' rosters, each with just
# the games he played there - player_season_stats() sums his whole season
# under his last team, which credited the old team's games to the new one.
_TEAM_ROSTER_SQL = _PLAYER_SEASON_SQL.replace(
    "    where season = ?\n", "    where season = ? and team_abbreviation = ?\n"
)
assert _TEAM_ROSTER_SQL != _PLAYER_SEASON_SQL


# The same season line for players found by name across every season: each
# matching player's most recent season with at least min_games games, plus a
# season column. Name matching ignores case and accents ("jokic" finds
# "Jokić"); contains() takes the text literally, so % or _ are not wildcards.
# Which season to show is picked from mart_player_season (a small table, one
# row per player-season; its games_played equals the game-log count), so the
# name search never folds a million game rows.
_LATEST_CTE = """
    with latest as (
        select player_id, max(season) as season
        from main_marts.mart_player_season
        where contains(strip_accents(lower(player_name)), ?)
          and games_played >= ?
        group by player_id
        order by season desc
        limit ?
    )
"""
_LATEST_MATCH_SQL = _LATEST_CTE + _PLAYER_SEASON_SQL.replace(
    "    select\n        player_id,\n", "    select\n        player_id,\n        season,\n"
).replace(
    "    from main_staging.stg_player_game_logs\n    where season = ?\n"
    "    group by player_id\n    having count(*) >= ?\n",
    "    from main_staging.stg_player_game_logs\n    join latest using (player_id, season)\n"
    "    group by player_id, season\n",
)
assert "join latest" in _LATEST_MATCH_SQL and "        season,\n" in _LATEST_MATCH_SQL

# team_label for those same player-seasons ("CHI → BOS" when traded), in one
# query rather than one player_team_paths() call per season found.
_LATEST_PATHS_SQL = (
    _LATEST_CTE
    + """
    select player_id, season,
           string_agg(team_abbreviation, ' → ' order by first_game) as team_label
    from (
        select player_id, season, team_abbreviation, min(game_date) as first_game
        from main_staging.stg_player_game_logs
        join latest using (player_id, season)
        group by player_id, season, team_abbreviation
    )
    group by player_id, season
"""
)


def player_latest_seasons(name: str, min_games: int = 1, limit: int = 30) -> pd.DataFrame:
    """Players whose name contains `name` (case and accents ignored), each
    at his most recent season with min_games+ games: the player_season_stats
    columns plus season and team_label. At most `limit` players, newest
    seasons first."""
    needle = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower().strip()
    params = (needle or "\x00", int(min_games), int(limit))  # "" would match everyone
    found = q(_LATEST_MATCH_SQL, params)
    if found.empty:
        return found.assign(team_label=pd.Series(dtype=str))
    return found.merge(q(_LATEST_PATHS_SQL, params), on=["player_id", "season"], how="left")


def team_roster(season: str, team: str, min_games: int = 1) -> pd.DataFrame:
    return q(_TEAM_ROSTER_SQL, (season, team, min_games))


def player_team_paths(season: str) -> pd.DataFrame:
    """Every team each player played for in a season, in order: player_id,
    team_path ("CHI → BOS"), n_teams. Ordered by each stint's first game."""
    return q(
        """
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
        """,
        (season,),
    )


def with_team_labels(
    stats: pd.DataFrame, season: str, id_col: str = "player_id", team_col: str = "team"
) -> pd.DataFrame:
    """A copy of a player-season frame with team_label: "CHI → BOS" for a
    player who changed teams mid-season, his one team otherwise. The season
    line itself still covers his whole season - this only makes that
    visible instead of filing it silently under the last team."""
    paths = player_team_paths(season)
    out = stats.merge(
        paths[["player_id", "team_path"]].rename(columns={"player_id": id_col}),
        on=id_col,
        how="left",
    )
    out["team_label"] = out["team_path"].where(out["team_path"].notna(), out[team_col])
    return out.drop(columns="team_path")


def qualification_threshold(stats: pd.DataFrame, full_season: int = 25) -> int:
    """Minimum games to appear on a rate-stat leaderboard.

    A fixed cut empties every leaderboard for the first weeks of a live
    season (nobody has 25 games in November), so scale it to how far the
    season has actually run - the same idea as the NBA's "share of team
    games played" rule - and cap it at the full-season number.
    """
    if stats.empty:
        return 0
    return max(1, min(full_season, int(stats["gp"].max() * 0.6)))


_PLAYER_CAREER_SQL = """
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


def player_career_stats(min_games: int = 1) -> pd.DataFrame:
    """One row per player pooled across every ingested season. `team` is the
    most recent; percentages are computed from summed makes/attempts."""
    return q(_PLAYER_CAREER_SQL, (min_games,))


def player_season_breakdown(player_id: int) -> pd.DataFrame:
    """Per-season averages for one player - drives the career trajectory chart.

    `shot_poss` (shooting possessions) is the correct weight for averaging
    TS% across seasons: a games-played weight would treat a low-volume year
    as equal to a high-volume one.
    """
    return q(
        """
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
        """,
        (player_id,),
    )


def player_game_log(player_id: int, season: str) -> pd.DataFrame:
    return q(
        """
        select * from main_staging.stg_player_game_logs
        where player_id = ? and season = ? order by game_date
        """,
        (player_id, season),
    )


def league_shooting_averages(season: str) -> pd.Series:
    df = q(
        """
        select
            round(sum(field_goals_made) / sum(field_goals_attempted) * 100, 1)       as fg_pct,
            round(sum(three_pointers_made) / nullif(sum(three_pointers_attempted), 0) * 100, 1) as fg3_pct,
            round(sum(free_throws_made) / sum(free_throws_attempted) * 100, 1)       as ft_pct
        from main_staging.stg_player_game_logs
        where season = ?
        """,
        (season,),
    )
    return df.iloc[0]


# --- Teams / games -------------------------------------------------------------


def standings(season: str) -> pd.DataFrame:
    """Standings for one season: record, scoring splits, conference and the
    last-five form string, ordered for playoff seeding.

    Reads dbt's mart_team_standings, which carries a real (if simplified -
    see the model's own comment) head-to-head tiebreak ahead of point
    differential and is the one place the conference map now lives. Falls
    back to computing directly from the staging views - the mart's exact
    logic before it existed - when the mart isn't in the warehouse yet (an
    older published copy, or a local build where dbt hasn't run). This
    function has no marts_available() guard of its own callers, and
    Overview and Teams call it unconditionally, so it must degrade itself
    rather than let a catalog error take either page down.
    """
    try:
        df = q(
            """
            select
                team_id,
                team_abbreviation as team,
                team_name,
                games_played       as gp,
                wins                as w,
                losses              as l,
                win_pct             as pct,
                points_per_game     as ppg,
                opp_points_per_game as opp_ppg,
                net_points          as net,
                conference          as conf,
                form
            from main_marts.mart_team_standings
            where season = ?
            order by win_pct desc, head_to_head desc, net_points desc, team_abbreviation asc
            """,
            (season,),
        )
        return df
    except duckdb.CatalogException:
        pass

    df = q(
        """
        with paired as (
            select t.*, o.points as opp_points
            from main_staging.stg_team_game_logs t
            join main_staging.stg_team_game_logs o
              on t.game_id = o.game_id and t.team_id <> o.team_id
            where t.season = ?
        )
        select
            team_id,
            any_value(team_abbreviation)               as team,
            any_value(team_name)                       as team_name,
            count(*)                                   as gp,
            cast(sum(case when is_win then 1 else 0 end) as int) as w,
            cast(sum(case when is_win then 0 else 1 end) as int) as l,
            round(avg(case when is_win then 1.0 else 0.0 end), 3) as pct,
            round(avg(points), 1)                      as ppg,
            round(avg(opp_points), 1)                  as opp_ppg,
            round(avg(points - opp_points), 1)         as net,
            substr(string_agg(win_loss, '' order by game_date desc), 1, 5) as form
        from paired
        group by team_id
        order by pct desc, net desc
        """,
        (season,),
    )
    df["conf"] = df["team"].map(conference)
    return df


def team_game_log(team_id: int, season: str) -> pd.DataFrame:
    return q(
        """
        select t.*, o.points as opp_points, o.team_abbreviation as opponent
        from main_staging.stg_team_game_logs t
        join main_staging.stg_team_game_logs o
          on t.game_id = o.game_id and t.team_id <> o.team_id
        where t.team_id = ? and t.season = ?
        order by t.game_date
        """,
        (team_id, season),
    )


def games_list(season: str) -> pd.DataFrame:
    # A handful of neutral-site games (NBA Cup, international) list both
    # teams as away ('@'), so rank rows per game instead of filtering on
    # 'vs.': the true home team ranks first when one exists, otherwise the
    # pick is deterministic and the game still appears exactly once.
    return q(
        """
        with ranked as (
            select *, row_number() over (
                partition by game_id
                order by (matchup like '%vs.%') desc, team_abbreviation
            ) as rn
            from main_staging.stg_team_game_logs
            where season = ?
        )
        select
            h.game_id,
            h.game_date,
            a.team_abbreviation as away, a.points as away_pts,
            h.team_abbreviation as home, h.points as home_pts
        from ranked h
        join ranked a on h.game_id = a.game_id and a.rn = 2
        where h.rn = 1
        order by h.game_date desc, h.game_id
        """,
        (season,),
    )


def pbp_game_ids() -> set[str]:
    return set(q("select distinct game_id from main_staging.stg_play_by_play")["game_id"])


def game_pbp(game_id: str) -> pd.DataFrame:
    return q(
        """
        select * from main_staging.stg_play_by_play
        where game_id = ? order by action_number
        """,
        (game_id,),
    )


def game_box_score(game_id: str) -> pd.DataFrame:
    return q(
        """
        select team_abbreviation as team, team_id, player_name as player,
               minutes_played as min, points as pts, total_rebounds as reb,
               assists as ast, steals as stl, blocks as blk, turnovers as tov,
               field_goals_made as fgm, field_goals_attempted as fga,
               three_pointers_made as tpm, three_pointers_attempted as tpa,
               free_throws_made as ftm, free_throws_attempted as fta,
               plus_minus
        from main_staging.stg_player_game_logs
        where game_id = ?
        order by minutes_played desc, points desc
        """,
        (game_id,),
    )


# --- Advanced metrics ----------------------------------------------------------

# Label -> (column, higher_is_better, help text). Drives the Advanced page so
# the metric list lives in one place instead of being restated per widget.
ADVANCED_METRICS: dict[str, tuple[str, bool, str]] = {
    "TS%": (
        "true_shooting_pct",
        True,
        "True shooting: points per shooting possession, counting 3s and free throws",
    ),
    "eFG%": (
        "effective_fg_pct",
        True,
        "Effective FG%: field goal percentage with 3-pointers weighted 1.5x",
    ),
    "USG%": (
        "usage_pct",
        True,
        "Usage: share of team possessions a player ends while on the floor",
    ),
    "AST%": (
        "assist_pct",
        True,
        "Assist rate: share of teammate field goals a player assisted while on the floor",
    ),
    "REB%": (
        "rebound_pct",
        True,
        "Rebound rate: share of available rebounds a player grabbed while on the floor",
    ),
    "TOV%": (
        "turnover_pct",
        False,
        "Turnover rate: turnovers per 100 individual plays (lower is better)",
    ),
    "STL%": ("steal_pct", True, "Steals per opponent possession while on the floor"),
    "BLK%": ("block_pct", True, "Share of opponent 2-point attempts blocked"),
    "PTS/36": ("points_per_36", True, "Points per 36 minutes, pace of a starter's night"),
    "PTS/100": ("points_per_100", True, "Points per 100 team possessions on the floor"),
    "Game score": (
        "game_score",
        True,
        "Hollinger game score: one-number box score summary, ~10 is average",
    ),
    "Net rating": (
        "net_rating",
        True,
        "Team point differential per 100 possessions with the player on the floor "
        "(official NBA figure, 1996-97 on)",
    ),
    "PIE": (
        "player_impact_estimate",
        True,
        "Player impact estimate: share of the game's total production "
        "(official NBA figure, 1996-97 on)",
    ),
}


@st.cache_data(ttl=600, show_spinner=False)
def marts_available() -> bool:
    """Whether dbt's marts are in the warehouse.

    The advanced views query `main_marts`, and a warehouse published before
    those models existed (or one where dbt has not been run) raises a
    catalog error that propagates out of the page and takes the whole app
    down with it. Callers check this first and show a message instead.
    """
    try:
        with duckdb.connect(str(DB_PATH), read_only=True) as con:
            con.execute("select 1 from main_marts.mart_player_season limit 1")
        return True
    except (duckdb.Error, OSError):
        return False


@st.cache_data(ttl=600, show_spinner=False)
def team_finances_available() -> bool:
    """Whether mart_team_finances exists in the warehouse - same guard pattern
    as marts_available()/predictions_available(), for a warehouse published
    before this feature shipped.

    Also probes main.salary_cap_history: finances.py's render() calls
    salary_cap_history() unconditionally right after this check passes, so
    this guard has to cover both objects the page actually reads, not just
    the mart, or a warehouse missing just the seed would still crash past
    this check."""
    try:
        with duckdb.connect(str(DB_PATH), read_only=True) as con:
            con.execute("select 1 from main_marts.mart_team_finances limit 1")
            con.execute("select 1 from main.salary_cap_history limit 1")
        return True
    except (duckdb.Error, OSError):
        return False


def team_payroll_history(franchise: str | None = None) -> pd.DataFrame:
    """Payroll vs. cap/tax/apron thresholds, one row per team-season.

    With a franchise key (see dashboard/lib/franchises.py), returns every
    season of that franchise under any code it has played under - OKC
    includes the 1984-2008 SEA rows, NOP the 1988-2002 CHH rows - annotated
    with franchise and era_name. The franchise mapping is season-aware, which
    a SQL `in (codes)` filter could not express, so it is applied here."""
    df = q("select * from main_marts.mart_team_finances order by season, team_abbreviation")
    if franchise is None:
        return df
    df = franchises.annotate(df)
    return df[df["franchise"] == franchise].reset_index(drop=True)


def salary_cap_history() -> pd.DataFrame:
    """League-wide cap/tax/apron thresholds by season, independent of any team."""
    return q(
        "select season, salary_cap, luxury_tax, first_apron, second_apron "
        "from main.salary_cap_history order by season"
    )


@st.cache_data(ttl=600, show_spinner=False)
def team_contracts_available() -> bool:
    """Whether mart_team_contracts exists - a warehouse published before
    per-player salaries were scraped has the finances mart but not this."""
    try:
        with duckdb.connect(str(DB_PATH), read_only=True) as con:
            con.execute("select 1 from main_marts.mart_team_contracts limit 1")
        return True
    except (duckdb.Error, OSError):
        return False


def team_contracts(season: str, team_abbreviation: str) -> pd.DataFrame:
    """One team-season's salaries, biggest first."""
    return q(
        "select player, salary_usd, salary_rank, share_of_payroll "
        "from main_marts.mart_team_contracts "
        "where season = ? and team_abbreviation = ? order by salary_rank",
        (season, team_abbreviation),
    )


@st.cache_data(ttl=600, show_spinner=False)
def predictions_available() -> bool:
    """Whether any predictions have been written yet.

    The table only exists after ml/predict.py has run at least once. A
    warehouse published before that raises a catalog error that would take
    the whole app down, so the page checks first - same pattern as
    marts_available().
    """
    try:
        with duckdb.connect(str(DB_PATH), read_only=True) as con:
            con.execute("select 1 from predictions limit 1")
        return True
    except (duckdb.Error, OSError):
        return False


def upcoming_predictions(limit: int = 30) -> pd.DataFrame:
    """The most recent prediction for each not-yet-played game."""
    return q(
        """
        with latest as (
            select *, row_number() over (
                partition by game_id order by predicted_at desc
            ) as recency
            from predictions
        )
        select l.game_id, l.game_date, s.tipoff_utc, l.win_probability,
               l.predicted_margin,
               s.home_team_abbreviation, s.away_team_abbreviation
        from latest l
        join main_staging.stg_schedule s on s.game_id = l.game_id
        where l.recency = 1 and s.game_status = 1
        order by l.game_date, l.game_id
        limit ?
        """,
        (limit,),
    )


# Same join ml.evaluate.settled_predictions() uses: only the earliest
# prediction per game (grading a later re-run would let a model be scored
# on a prediction made after the result was known), joined to the actual
# result. Duplicated here rather than imported - see prediction_track_record's
# docstring for why.
_SETTLED_PREDICTIONS_SQL = """
    with first_prediction as (
        select *, row_number() over (
            partition by game_id order by predicted_at
        ) as attempt
        from predictions
    )
    select p.game_id, p.game_date, p.predicted_margin, p.win_probability,
           f.margin, f.home_won, f.home_points, f.away_points
    from first_prediction p
    join main_marts.fct_team_game f on f.game_id = p.game_id
    where p.attempt = 1
      -- Same no-contest exclusion the rest of the pipeline applies: a
      -- cancelled game recorded as a 0-0 final is not a result, and
      -- grading a prediction for it would show a miss on the public
      -- track record for a game that never happened.
      and not (f.home_points = 0 and f.away_points = 0)
"""


def prediction_track_record() -> dict:
    """The model's public accuracy record: accuracy, Brier score, margin
    MAE and n, computed directly here with plain pandas/numpy.

    Deliberately does NOT import ml.evaluate or ml.train, even though
    ml.evaluate.track_record() computes the identical numbers. ml.train
    imports scipy and sklearn at module level, and those are dev-only
    dependencies (see requirements-dev.txt) - Streamlit Community Cloud's
    build only installs requirements.txt, which does not have them. This
    module previously imported ml.evaluate here, which meant the app
    crashed with ModuleNotFoundError the moment a real predictions table
    existed in a warehouse published to the cloud deploy - the exact
    "must degrade gracefully" case this function exists for. The three
    lines of metric math below are cheap enough to duplicate rather than
    drag a training-dependency import into a dashboard image for.

    Returns {"n": 0} when nothing has settled yet, including when the
    predictions table (or a mart it joins against) does not exist - the
    page must degrade the same gentle way predictions_available() does
    rather than let a catalog error escape. Only catches CatalogException
    (the real "table doesn't exist" condition) - a BinderException from
    schema drift, a ConversionException, or an IOException from a
    truncated download must still surface as a real error rather than
    silently reading as "no predictions yet".
    """
    if not predictions_available():
        return {"n": 0}
    try:
        settled = q(_SETTLED_PREDICTIONS_SQL)
    except duckdb.CatalogException:
        return {"n": 0}
    if settled.empty:
        return {"n": 0}

    home_won = settled["home_won"].astype(bool).to_numpy()
    win_probability = settled["win_probability"].astype(float).to_numpy()
    predicted_margin = settled["predicted_margin"].astype(float).to_numpy()
    margin = settled["margin"].astype(float).to_numpy()

    # A coin flip (exactly 0.5) counts as a home pick, the same rule the
    # page's cards and recent-results grid use.
    return {
        "accuracy": float(((win_probability >= 0.5) == home_won).mean()),
        "brier": float(np.mean((win_probability - home_won.astype(float)) ** 2)),
        "margin_mae": float(np.mean(np.abs(predicted_margin - margin))),
        "n": len(settled),
    }


def recent_settled_predictions(n: int = 20) -> pd.DataFrame:
    """The latest graded predictions, newest first: who played, the final
    score, what the model said and whether it called the winner. Uses the same
    earliest-prediction-per-game join as the track record. Empty when nothing
    has settled (or the warehouse predates the tables it needs)."""
    cols = [
        "game_date",
        "home",
        "away",
        "home_pts",
        "away_pts",
        "win_probability",
        "predicted_margin",
        "correct",
    ]
    if not predictions_available():
        return pd.DataFrame(columns=cols)
    try:
        df = q(
            f"""
            select s.game_date, s.home_team_abbreviation as home,
                   s.away_team_abbreviation as away,
                   t.home_points as home_pts, t.away_points as away_pts,
                   t.win_probability, t.predicted_margin,
                   (t.win_probability >= 0.5) = t.home_won as correct
            from ({_SETTLED_PREDICTIONS_SQL}) t
            join main_staging.stg_schedule s on s.game_id = t.game_id
            order by s.game_date desc, t.game_id
            limit ?
            """,
            (n,),
        )
    except duckdb.CatalogException:
        return pd.DataFrame(columns=cols)
    df["correct"] = df["correct"].astype(bool)
    return df


def calibration_bins(bins: int = 10) -> pd.DataFrame:
    """Does "70%" mean 70%? Settled games bucketed by predicted home-win
    probability into equal-width bins on [0, 1]; per bin the mean predicted
    probability, the share the home team actually won, and the game count.
    Empty bins are dropped, and nothing is returned below 50 settled games
    because a bin of three games is noise, not calibration."""
    cols = ["bin_mid", "predicted_mean", "actual_rate", "n"]
    if not predictions_available():
        return pd.DataFrame(columns=cols)
    try:
        settled = q(_SETTLED_PREDICTIONS_SQL)
    except duckdb.CatalogException:
        return pd.DataFrame(columns=cols)
    if len(settled) < 50:
        return pd.DataFrame(columns=cols)

    prob = settled["win_probability"].astype(float).to_numpy()
    won = settled["home_won"].astype(bool).astype(float).to_numpy()
    # p == 1.0 belongs in the top bin, not a phantom eleventh.
    idx = np.minimum((prob * bins).astype(int), bins - 1)
    frame = pd.DataFrame({"bin": idx, "p": prob, "won": won})
    out = (
        frame.groupby("bin")
        .agg(predicted_mean=("p", "mean"), actual_rate=("won", "mean"), n=("p", "size"))
        .reset_index()
    )
    out["bin_mid"] = (out["bin"] + 0.5) / bins
    return out[cols]


def player_advanced(season: str, min_minutes: int = 0) -> pd.DataFrame:
    """Advanced metrics for one season. Rate stats are meaningless on tiny
    samples (one made three is a 150% TS%), so callers pass a minutes floor."""
    return q(
        """
        select * from main_marts.mart_player_season
        where season = ? and minutes >= ?
        """,
        (season, min_minutes),
    )


def player_advanced_career(player_id: int) -> pd.DataFrame:
    """Every season of advanced metrics for one player, oldest first."""
    return q(
        """
        select * from main_marts.mart_player_season
        where player_id = ? order by season
        """,
        (player_id,),
    )


def team_advanced(season: str) -> pd.DataFrame:
    return q(
        """
        select * from main_marts.mart_team_season
        where season = ? order by net_rating desc nulls last
        """,
        (season,),
    )


def advanced_seasons() -> list[str]:
    """Seasons where the box score is complete enough for advanced metrics
    (1985-86 on). Earlier seasons are missing whole columns at the source."""
    return q(
        """
        select distinct season from main_marts.mart_player_season
        where box_score_complete order by 1 desc
        """
    )["season"].tolist()


def percentile_of(series: pd.Series, value: float, higher_is_better: bool = True) -> float | None:
    """Where `value` sits in `series`, 0-100. Used to answer "is 36% from three
    good" with a rank instead of a bare league average."""
    clean = series.dropna()
    if not len(clean) or value != value:
        return None
    pct = (clean < value).sum() / len(clean) * 100
    return pct if higher_is_better else 100 - pct


# --- Arcade -------------------------------------------------------------------


@st.cache_data(ttl=600, show_spinner=False)
def player_ages_available() -> bool:
    """Whether stg_player_advanced has the age column (a warehouse published
    before it was added does not)."""
    try:
        with duckdb.connect(str(DB_PATH), read_only=True) as con:
            con.execute("select age from main_staging.stg_player_advanced limit 1")
        return True
    except (duckdb.Error, OSError):
        return False


_ARCADE_POOL_SQL = """
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
"""

# Age per player-season. The NBA's own age exists from 1996-97 (the advanced
# stats); an earlier season counts back from the player's first known age,
# a year per season (Jordan, 33 in 1996-97, was 25 in 1988-89). A career
# that ended before 1996-97 has no age.
_ARCADE_AGES_SQL = """
    select p.*,
           cast(floor(coalesce(adv.age, anchor.age0
                + (cast(left(p.season, 4) as int) - anchor.y0))) as int) as age
    from ({pool}) p
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


def arcade_pool(min_gp: int = 50, min_ppg: float = 14.0) -> pd.DataFrame:
    """Notable player-seasons across every ingested season - the pool both
    games draw from. One row per player per season, with the player's age
    that season where known (null otherwise, or on an older warehouse)."""
    if player_ages_available():
        return q(_ARCADE_AGES_SQL.format(pool=_ARCADE_POOL_SQL), (min_gp, min_ppg))
    # pandas-stubs leave NAType out of assign()'s accepted scalars.
    return q(_ARCADE_POOL_SQL, (min_gp, min_ppg)).assign(age=pd.NA)  # type: ignore[arg-type]


@st.cache_data(ttl=600, show_spinner=False)
def player_impact_available() -> bool:
    """Whether the team builder's tables exist - a warehouse published before
    ml/player_impact.py first ran has neither."""
    try:
        with duckdb.connect(str(DB_PATH), read_only=True) as con:
            con.execute("select 1 from main.player_impact limit 1")
            con.execute("select 1 from main.player_impact_meta limit 1")
        return True
    except (duckdb.Error, OSError):
        return False


def player_impact_pool(season: str | None) -> pd.DataFrame:
    """The team builder's pool: one season's player-seasons, or every season
    when `season` is None, best impact first."""
    cols = "season, player_id, player, team, gp, mpg, ppg, rpg, apg, impact, usage, cost"
    if season is None:
        return q(f"select {cols} from main.player_impact order by impact desc, player_id, season")
    return q(
        f"select {cols} from main.player_impact where season = ? order by impact desc, player_id",
        (season,),
    )


def player_impact_meta() -> dict:
    """The impact model's single metadata row (calibration, league usage
    total, fit quality) as a dict; empty if the table has no row."""
    df = q("select * from main.player_impact_meta limit 1")
    return df.iloc[0].to_dict() if len(df) else {}


def all_team_net_ratings() -> pd.DataFrame:
    """Every team-season's net rating from 1985-86 on (season, team,
    net_rating), oldest first. The Arcade's all-time Build mode draws its
    opponents from these; 1985-86 is where the impact pool starts too."""
    return q(
        """
        select season, team_abbreviation as team, net_rating
        from main_marts.mart_team_season
        where season >= '1985-86' and net_rating is not null
        order by season, team_abbreviation
        """
    )
