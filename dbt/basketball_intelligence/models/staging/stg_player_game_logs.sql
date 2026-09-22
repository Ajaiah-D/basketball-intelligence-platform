-- One row per player per game. Cleans and types the raw LeagueGameLog
-- (player mode) response.

with cleaned as (

    select
        cast(season_id as varchar)          as season_id,
        cast(season as varchar)             as season,
        cast(player_id as bigint)           as player_id,
        cast(player_name as varchar)        as player_name,
        cast(team_id as bigint)             as team_id,
        cast(team_abbreviation as varchar)  as team_abbreviation,
        cast(team_name as varchar)          as team_name,
        cast(game_id as varchar)            as game_id,
        cast(game_date as date)             as game_date,
        cast(matchup as varchar)            as matchup,
        matchup like '%@%'                  as is_away_game,
        cast(wl as varchar)                 as win_loss,
        wl = 'W'                            as is_win,
        cast(min as integer)                as minutes_played,
        cast(fgm as integer)                as field_goals_made,
        cast(fga as integer)                as field_goals_attempted,
        cast(fg_pct as double)              as field_goal_pct,
        cast(fg3m as integer)               as three_pointers_made,
        cast(fg3a as integer)               as three_pointers_attempted,
        cast(fg3_pct as double)             as three_point_pct,
        cast(ftm as integer)                as free_throws_made,
        cast(fta as integer)                as free_throws_attempted,
        cast(ft_pct as double)              as free_throw_pct,
        cast(oreb as integer)               as offensive_rebounds,
        cast(dreb as integer)               as defensive_rebounds,
        cast(reb as integer)                as total_rebounds,
        cast(ast as integer)                as assists,
        cast(stl as integer)                as steals,
        cast(blk as integer)                as blocks,
        cast(tov as integer)                as turnovers,
        cast(pf as integer)                 as personal_fouls,
        cast(pts as integer)                as points,
        cast(plus_minus as integer)         as plus_minus,
        cast(fantasy_pts as double)         as fantasy_points
    from {{ source('raw', 'player_game_logs') }}

),

-- The source lists four players under both teams in one game (identical
-- box scores, different team_id) - a Dwight Jones 1979-80 game and three
-- 1982-83 games. Left alone these double-count a game in every career
-- total. Keep the row for whichever team the player logged more games
-- with that season; ties break on team_id so the result is stable.
-- DuckDB does not allow a window function inside another window function's
-- OVER clause, so the per-team season game count is computed here first
-- and only referenced (not nested) in the dedup ranking below.
with_team_season_games as (

    select
        *,
        count(*) over (
            partition by season, player_id, team_id
        ) as team_season_games
    from cleaned

)

select
    * exclude (team_season_games)
from with_team_season_games
qualify row_number() over (
    partition by game_id, player_id
    order by team_season_games desc, team_id
) = 1
