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
        round(avg(plus_minus), 1)             as plus_minus
    from main_staging.stg_player_game_logs
    where season = ?
    group by player_id
    having count(*) >= ?
"""


def player_season_stats(season: str, min_games: int = 1) -> pd.DataFrame:
    return q(_PLAYER_SEASON_SQL, (season, min_games))


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


# --- Advanced metrics ----------------------------------------------------------

# Label -> (column, higher_is_better, help text). Drives the Advanced page so
# the metric list lives in one place instead of being restated per widget.
ADVANCED_METRICS: dict[str, tuple[str, bool, str]] = {
    "TS%": ("true_shooting_pct", True,
            "True shooting: points per shooting possession, counting 3s and free throws"),
    "eFG%": ("effective_fg_pct", True,
             "Effective FG%: field goal percentage with 3-pointers weighted 1.5x"),
    "USG%": ("usage_pct", True,
             "Usage: share of team possessions a player ends while on the floor"),
    "AST%": ("assist_pct", True,
             "Assist rate: share of teammate field goals a player assisted while on the floor"),
    "REB%": ("rebound_pct", True,
             "Rebound rate: share of available rebounds a player grabbed while on the floor"),
    "TOV%": ("turnover_pct", False,
             "Turnover rate: turnovers per 100 individual plays (lower is better)"),
    "STL%": ("steal_pct", True, "Steals per opponent possession while on the floor"),
    "BLK%": ("block_pct", True, "Share of opponent 2-point attempts blocked"),
    "PTS/36": ("points_per_36", True, "Points per 36 minutes, pace of a starter's night"),
    "PTS/100": ("points_per_100", True, "Points per 100 team possessions on the floor"),
    "Game score": ("game_score", True,
                   "Hollinger game score: one-number box score summary, ~10 is average"),
    "Net rating": ("net_rating", True,
                   "Team point differential per 100 possessions with the player on the floor "
                   "(official NBA figure, 1996-97 on)"),
    "PIE": ("player_impact_estimate", True,
            "Player impact estimate: share of the game's total production "
            "(official NBA figure, 1996-97 on)"),
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
        select l.game_id, l.game_date, l.win_probability, l.predicted_margin,
               s.home_team_abbreviation, s.away_team_abbreviation
        from latest l
        join main_staging.stg_schedule s on s.game_id = l.game_id
        where l.recency = 1 and s.game_status = 1
        order by l.game_date, l.game_id
        limit ?
        """,
        (limit,),
    )


def prediction_track_record() -> dict:
    """The model's public accuracy record.

    Returns {"n": 0} when nothing has settled yet, including when the
    predictions table (or a mart it joins against) does not exist - the
    page must degrade the same gentle way predictions_available() does
    rather than let a catalog error escape.
    """
    if not predictions_available():
        return {"n": 0}
    from ml.evaluate import track_record

    try:
        with duckdb.connect(str(DB_PATH), read_only=True) as con:
            return track_record(con)
    except duckdb.Error:
        return {"n": 0}


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
