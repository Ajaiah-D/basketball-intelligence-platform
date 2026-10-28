-- One row per player per game: his box score line beside the game's
-- result, for the Players page's game log and game-by-game trend.
--
-- True shooting is per game here, by the same formula as the season line
-- (player_stat_line): null when he took no shots and no free throws, and
-- when the source is missing an input. shot_poss is its weight: averaging
-- per-game true shooting over shot_poss gives the true shooting of those
-- games together, which is how the trend's rolling line and any season
-- figure have to combine them.
--
-- A view, like the staging model under it: the table would copy a million
-- rows into the published warehouse for a page that reads one player's
-- season at a time.
--
-- The left join keeps a game the team logs don't have (the source has had
-- such gaps; see assert_player_season_matches_game_logs): its score is null
-- and the opponent comes from the matchup string instead.

{{ config(materialized='view') }}

select
    p.season,
    p.game_id,
    p.game_date,
    p.player_id,
    p.player_name,
    p.team_id,
    p.team_abbreviation,
    coalesce(o.opp_team_abbreviation, right(p.matchup, 3))  as opp_team_abbreviation,
    p.is_away_game,
    p.is_win,
    o.points                                                as team_points,
    o.opp_points,
    p.minutes_played,
    p.points,
    p.total_rebounds,
    p.assists,
    p.three_pointers_made,
    p.field_goals_attempted,
    p.free_throws_attempted,
    case when p.field_goals_attempted is null
              or p.free_throws_attempted is null
              or p.points is null then null
         else round(p.points / nullif(2 * (p.field_goals_attempted
              + 0.44 * p.free_throws_attempted), 0) * 100, 1)
    end                                                     as true_shooting_pct,
    p.field_goals_attempted + 0.44 * p.free_throws_attempted as shot_poss,
    p.plus_minus
from {{ ref('stg_player_game_logs') }} p
left join {{ ref('int_team_game_opponent') }} o
       on o.game_id = p.game_id
      and o.team_id = p.team_id
