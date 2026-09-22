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
