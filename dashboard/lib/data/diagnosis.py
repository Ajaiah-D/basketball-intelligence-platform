"""The numbers behind the diagnosis views: each team's profile of league
ranks, the rotation behind it (the player breakdown), one player's
percentiles, and the player scatter's source.

The three marts these read (mart_team_profile, mart_player_percentiles,
mart_player_defense) are newer than some published warehouses, so a page
checks profile_available() before calling anything else here.
league_player_rows() reads only mart_player_season and works on any
warehouse.
"""

from __future__ import annotations

import pandas as pd

from .core import objects_exist, q

PROFILE_MARTS = (
    "main_marts.mart_team_profile",
    "main_marts.mart_player_percentiles",
    "main_marts.mart_player_defense",
)

# The rotation: players with this many games for the team.
ROTATION_MIN_GAMES = 10


def profile_available() -> bool:
    """Whether the warehouse has all three diagnosis marts. A warehouse
    published before them has none, and the pages show a notice instead."""
    return objects_exist(*PROFILE_MARTS)


def team_profile(season: str) -> pd.DataFrame:
    """Every team in `season` with each profile stat, its league rank
    (`<stat>_rank`, 1 = best) and percentile (`<stat>_pctile`)."""
    return q(
        """
        select *
        from main_marts.mart_team_profile
        where season = ?
        order by team_abbreviation
        """,
        (season,),
    )


def team_drivers(season: str, team: str) -> pd.DataFrame:
    """The team's rotation in `season` (10+ games for it), most minutes
    first, with every measure diagnosis.AREAS reads.

    Games, minutes and the three-point volume and accuracy are the player's
    stint with this team (mart_player_team_season); team_three_pa_share is
    his share of the team's three-point attempts that season, out of every
    player who took one for it. The other rates are his whole season
    (mart_player_season), so a traded player's include his other team.
    The on/off estimate and fouls come from mart_player_defense.

    Each measure also has `<measure>_league_median`, the same on every row:
    the median over that season's qualified players
    (mart_player_percentiles.is_qualified), over their season values.
    """
    return q(
        """
        with stints as (
            select *
            from main_marts.mart_player_team_season
            where season = ? and team_abbreviation = ?
        ),

        team_threes as (
            select sum(tpa_total) as team_tpa
            from stints
        ),

        -- The stint mart has per-game minutes only; the total is summed
        -- from the same game logs it is built from.
        stint_minutes as (
            select player_id, team_id, sum(minutes_played) as minutes
            from main_staging.stg_player_game_logs
            where season = ? and team_abbreviation = ?
            group by player_id, team_id
        ),

        qualified as (
            select s.*, d.def_on_minus_off, d.fouls_per_36
            from main_marts.mart_player_percentiles p
            join main_marts.mart_player_season s
              on s.season = p.season and s.player_id = p.player_id
            left join main_marts.mart_player_defense d
                   on d.season = p.season and d.player_id = p.player_id
            where p.season = ? and p.is_qualified
        ),

        medians as (
            select
                median(true_shooting_pct)      as true_shooting_pct_league_median,
                median(usage_pct)              as usage_pct_league_median,
                median(three_pa_per_game)      as three_pa_per_game_league_median,
                median(fg3_pct)                as fg3_pct_league_median,
                median(turnover_pct)           as turnover_pct_league_median,
                median(offensive_rebound_pct)  as offensive_rebound_pct_league_median,
                median(defensive_rebound_pct)  as defensive_rebound_pct_league_median,
                median(free_throw_rate)        as free_throw_rate_league_median,
                median(assist_pct)             as assist_pct_league_median,
                median(steal_pct)              as steal_pct_league_median,
                median(block_pct)              as block_pct_league_median,
                median(def_on_minus_off)       as def_on_minus_off_league_median,
                median(fouls_per_36)           as fouls_per_36_league_median
            from qualified
        )

        select
            st.player_id,
            st.player_name                                   as player,
            s.team_label,
            st.games_played,
            m.minutes,
            st.minutes_per_game,
            st.three_pa_per_game,
            st.fg3_pct,
            round(st.tpa_total / nullif(tt.team_tpa, 0), 3)   as team_three_pa_share,
            s.true_shooting_pct,
            s.usage_pct,
            s.turnover_pct,
            s.offensive_rebound_pct,
            s.defensive_rebound_pct,
            s.free_throw_rate,
            s.assist_pct,
            s.steal_pct,
            s.block_pct,
            d.on_court_def_rating,
            d.est_off_court_def_rating,
            d.def_on_minus_off,
            d.fouls_per_36,
            p.is_qualified,
            p.true_shooting_pct_pctile,
            p.usage_pct_pctile,
            p.turnover_pct_pctile,
            p.offensive_rebound_pct_pctile,
            p.defensive_rebound_pct_pctile,
            p.free_throw_rate_pctile,
            p.assist_pct_pctile,
            p.steal_pct_pctile,
            p.block_pct_pctile,
            md.*
        from stints st
        cross join team_threes tt
        cross join medians md
        left join stint_minutes m
               on m.player_id = st.player_id and m.team_id = st.team_id
        left join main_marts.mart_player_season s
               on s.season = st.season and s.player_id = st.player_id
        left join main_marts.mart_player_percentiles p
               on p.season = st.season and p.player_id = st.player_id
        left join main_marts.mart_player_defense d
               on d.season = st.season and d.player_id = st.player_id
        where st.games_played >= ?
        order by m.minutes desc nulls last, st.player_name, st.player_id
        """,
        (season, team, season, team, season, ROTATION_MIN_GAMES),
    )


def player_percentiles(season: str, player_id: int) -> pd.Series | None:
    """The player's mart_player_percentiles row for `season` (values,
    `<measure>_pctile` and is_qualified), or None when he has none."""
    df = q(
        """
        select *
        from main_marts.mart_player_percentiles
        where season = ? and player_id = ?
        """,
        (season, int(player_id)),
    )
    return None if df.empty else df.iloc[0]


def league_player_rows(season: str, min_games: int) -> pd.DataFrame:
    """Every player in `season` with min_games+ games and each stat the
    player scatter offers, under mart_player_season's names, plus team (his
    last) and team_label (every team, "CHI → BOS")."""
    return q(
        """
        select
            player_id,
            player_name             as player,
            team,
            team_label,
            games_played,
            minutes_per_game,
            points_per_game,
            rebounds_per_game,
            assists_per_game,
            steals_per_game,
            blocks_per_game,
            threes_made_per_game,
            true_shooting_pct,
            effective_fg_pct,
            usage_pct,
            assist_pct,
            rebound_pct,
            turnover_pct,
            steal_pct,
            block_pct,
            three_point_attempt_rate,
            free_throw_rate,
            plus_minus_per_game     as plus_minus,
            player_impact_estimate,
            game_score
        from main_marts.mart_player_season
        where season = ? and games_played >= ?
        order by player_id
        """,
        (season, int(min_games)),
    )
