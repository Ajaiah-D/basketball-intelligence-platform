-- Team game logs joined to the opponent's row for the same game, so every
-- downstream model gets both sides without repeating the self-join. Still
-- two rows per game (one per team); fct_team_game collapses it to one.

select
    t.season,
    t.game_id,
    t.game_date,
    t.team_id,
    t.team_abbreviation,
    t.matchup,
    t.is_away_game,
    t.is_win,
    t.points,
    t.field_goals_attempted,
    t.free_throws_attempted,
    t.offensive_rebounds,
    t.turnovers,
    o.team_id             as opp_team_id,
    o.team_abbreviation   as opp_team_abbreviation,
    o.points              as opp_points,
    o.offensive_rebounds  as opp_offensive_rebounds
from {{ ref('stg_team_game_logs') }} t
join {{ ref('stg_team_game_logs') }} o
  on t.game_id = o.game_id
 and t.team_id <> o.team_id
