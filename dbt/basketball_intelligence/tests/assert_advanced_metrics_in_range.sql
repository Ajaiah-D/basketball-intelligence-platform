-- Guards against the failure mode that produced a 145 offensive rating and
-- an 800 eFG% during development: sum() silently skipping nulls in seasons
-- where the source is missing whole columns. Any row here means a metric is
-- being computed from data that is not actually there.
--
-- Both sides need a sample-size floor, or this fails on legitimate data in
-- the opening weeks of a season and takes the weekly refresh down with it
-- (weekly_refresh.py stops at the first failed step and never publishes).
-- Measured against 2025-26: one team finished its first game on a 137
-- offensive rating, and a single made three-pointer is a 150% true
-- shooting percentage. Ten team games and 500 player minutes are past the
-- point where either can happen.

select 'team ' || metric as check, season, entity, value
from (
    select season, team_abbreviation as entity, 'offensive_rating' as metric,
           offensive_rating as value from {{ ref('mart_team_season') }}
    where games_played >= 10
    union all
    select season, team_abbreviation, 'defensive_rating', defensive_rating
    from {{ ref('mart_team_season') }} where games_played >= 10
    union all
    select season, team_abbreviation, 'pace', pace
    from {{ ref('mart_team_season') }} where games_played >= 10
    union all
    select season, team_abbreviation, 'effective_fg_pct', effective_fg_pct
    from {{ ref('mart_team_season') }} where games_played >= 10
)
where value is not null
  and (
       (metric in ('offensive_rating', 'defensive_rating') and (value < 80 or value > 130))
    or (metric = 'pace' and (value < 80 or value > 120))
    or (metric = 'effective_fg_pct' and (value < 35 or value > 65))
  )

union all

select 'player ' || metric, season, entity, value
from (
    select season, player_name as entity, 'true_shooting_pct' as metric,
           true_shooting_pct as value from {{ ref('mart_player_season') }}
    where minutes >= 500
    union all
    select season, player_name, 'usage_pct', usage_pct
    from {{ ref('mart_player_season') }} where minutes >= 500
    union all
    select season, player_name, 'rebound_pct', rebound_pct
    from {{ ref('mart_player_season') }} where minutes >= 500
)
where value is not null
  and (
       (metric = 'true_shooting_pct' and (value < 20 or value > 100))
    or (metric = 'usage_pct' and (value < 0 or value > 60))
    or (metric = 'rebound_pct' and (value < 0 or value > 40))
  )

union all

-- Published rates must look like percentages. A value outside these bounds
-- means the source changed shape or a cast silently truncated. Same
-- sample-size reasoning as above: a early-season row can be genuinely
-- extreme without being wrong.
select 'stg_' || model || ' ' || metric, season, entity, value
from (
    select season, cast(player_id as varchar) as entity, 'usage_pct' as metric,
           usage_pct as value, 'player_advanced' as model
    from {{ ref('stg_player_advanced') }}
    where games_played * minutes_per_game >= 500
    union all
    select season, cast(team_id as varchar), 'pace', pace, 'team_advanced'
    from {{ ref('stg_team_advanced') }}
    where games_played >= 10
)
where value is not null
  and (
       (metric = 'usage_pct' and (value < 0 or value > 60))
    or (metric = 'pace' and (value < 80 or value > 120))
  )

union all

-- The season-line marts. A league percentage is pooled over a whole season,
-- so it moves a few points at most (1979-80 to 2025-26: FG% 43.7-49.2, 3P%
-- 24.2-36.7, FT% 72.8-78.4); far outside that, a column went missing. An age
-- counted back from a bad anchor would land outside a playing career. Career
-- true shooting gets the same bounds as a season's, past 100 games.
select 'line ' || metric, season, entity, value
from (
    select season, 'league' as entity, 'league fg_pct' as metric, fg_pct as value
    from {{ ref('mart_league_shooting') }}
    union all
    select season, 'league', 'league fg3_pct', fg3_pct from {{ ref('mart_league_shooting') }}
    union all
    select season, 'league', 'league ft_pct', ft_pct from {{ ref('mart_league_shooting') }}
    union all
    select season, player_name, 'age', age from {{ ref('mart_player_season') }}
    union all
    select last_season, player_name, 'career true_shooting_pct', true_shooting_pct
    from {{ ref('mart_player_career') }} where games_played >= 100
)
where value is not null
  and (
       (metric = 'league fg_pct' and (value < 40 or value > 55))
    or (metric = 'league fg3_pct' and (value < 20 or value > 45))
    or (metric = 'league ft_pct' and (value < 65 or value > 85))
    or (metric = 'age' and (value < 17 or value > 50))
    or (metric = 'career true_shooting_pct' and (value < 20 or value > 100))
  )

union all

-- A shooting percentage is makes over attempts from the same games, so it
-- can't leave 0-100 on any sample, however small. Outside it means the two
-- sides were summed over different games again - the sum()-skips-nulls
-- trap that once gave 1980-81 seasons 1080% from the field.
select 'shooting ' || metric, season, entity, value
from (
    select season, player_name as entity, 'season fg_pct' as metric, fg_pct as value
    from {{ ref('mart_player_season') }}
    union all
    select season, player_name, 'season fg3_pct', fg3_pct from {{ ref('mart_player_season') }}
    union all
    select season, player_name, 'season ft_pct', ft_pct from {{ ref('mart_player_season') }}
    union all
    select season, player_name || ' ' || team_abbreviation, 'stint fg_pct', fg_pct
    from {{ ref('mart_player_team_season') }}
    union all
    select season, player_name || ' ' || team_abbreviation, 'stint fg3_pct', fg3_pct
    from {{ ref('mart_player_team_season') }}
    union all
    select season, player_name || ' ' || team_abbreviation, 'stint ft_pct', ft_pct
    from {{ ref('mart_player_team_season') }}
    union all
    select last_season, player_name, 'career fg_pct', fg_pct from {{ ref('mart_player_career') }}
    union all
    select last_season, player_name, 'career fg3_pct', fg3_pct from {{ ref('mart_player_career') }}
    union all
    select last_season, player_name, 'career ft_pct', ft_pct from {{ ref('mart_player_career') }}
    union all
    select season, 'league', 'league fg_pct', fg_pct from {{ ref('mart_league_shooting') }}
    union all
    select season, 'league', 'league fg3_pct', fg3_pct from {{ ref('mart_league_shooting') }}
    union all
    select season, 'league', 'league ft_pct', ft_pct from {{ ref('mart_league_shooting') }}
)
where value < 0 or value > 100
