-- Guards against the failure mode that produced a 145 offensive rating and
-- an 800 eFG% during development: sum() silently skipping nulls in seasons
-- where the source is missing whole columns. Any row here means a metric is
-- being computed from data that is not actually there.
--
-- Team-seasons are checked unconditionally. Players are checked only above
-- 500 minutes, since tiny samples produce legitimately extreme rates (one
-- made three-pointer on the season is a 150% true shooting percentage).

select 'team ' || metric as check, season, entity, value
from (
    select season, team_abbreviation as entity, 'offensive_rating' as metric,
           offensive_rating as value from {{ ref('mart_team_season') }}
    union all
    select season, team_abbreviation, 'defensive_rating', defensive_rating
    from {{ ref('mart_team_season') }}
    union all
    select season, team_abbreviation, 'pace', pace from {{ ref('mart_team_season') }}
    union all
    select season, team_abbreviation, 'effective_fg_pct', effective_fg_pct
    from {{ ref('mart_team_season') }}
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
