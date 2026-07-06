"""Read-only data access for the dashboard. All queries hit the DuckDB
warehouse's staging views and are cached by Streamlit. Explore pages are
season-scoped; the Arcade pulls from every ingested season."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
import streamlit as st

DB_PATH = Path(__file__).resolve().parents[2] / "warehouse" / "basketball.duckdb"

# nba_api's static team data has no conference field, so map it here.
# Covers current franchises; historical abbreviations fall back to East
# only if listed (SEA/VAN etc. handled below).
EAST = {"ATL", "BOS", "BKN", "NJN", "CHA", "CHH", "CHI", "CLE", "DET", "IND",
        "MIA", "MIL", "NYK", "ORL", "PHI", "TOR", "WAS", "WSB"}
WEST = {"DAL", "DEN", "GSW", "HOU", "LAC", "SDC", "LAL", "MEM", "VAN", "MIN",
        "NOP", "NOH", "NOK", "OKC", "SEA", "PHX", "POR", "SAC", "KCK", "SAS",
        "UTA", "UTH"}


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
    return q(
        "select distinct season from main_staging.stg_team_game_logs order by 1 desc"
    )["season"].tolist()


def latest_season() -> str:
    return seasons()[0]


# --- Player stats -------------------------------------------------------------

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
        round(sum(points) / nullif(2 * (sum(field_goals_attempted)
              + 0.44 * sum(free_throws_attempted)), 0) * 100, 1)                            as ts_pct,
        round(avg(plus_minus), 1)             as plus_minus
    from main_staging.stg_player_game_logs
    where season = ?
    group by player_id
    having count(*) >= ?
"""


def player_season_stats(season: str, min_games: int = 1) -> pd.DataFrame:
    return q(_PLAYER_SEASON_SQL, (season, min_games))


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
        round(sum(points) / nullif(2 * (sum(field_goals_attempted)
              + 0.44 * sum(free_throws_attempted)), 0) * 100, 1)                            as ts_pct,
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
    """Per-season averages for one player - drives the career trajectory chart."""
    return q(
        """
        select
            season,
            max_by(team_abbreviation, game_date) as team,
            count(*)                             as gp,
            round(avg(points), 1)                as ppg,
            round(avg(total_rebounds), 1)        as rpg,
            round(avg(assists), 1)               as apg,
            round(avg(three_pointers_made), 1)   as tpg
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
        select team_abbreviation as team, player_name as player,
               minutes_played as min, points as pts, total_rebounds as reb,
               assists as ast, steals as stl, blocks as blk,
               field_goals_made as fgm, field_goals_attempted as fga,
               three_pointers_made as tpm, three_pointers_attempted as tpa,
               plus_minus
        from main_staging.stg_player_game_logs
        where game_id = ?
        order by points desc
        """,
        (game_id,),
    )


# --- Arcade -------------------------------------------------------------------

def arcade_pool(min_gp: int = 50, min_ppg: float = 14.0) -> pd.DataFrame:
    """Notable player-seasons across every ingested season - the pool both
    games draw from. One row per player per season."""
    return q(
        """
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
        """,
        (min_gp, min_ppg),
    )
