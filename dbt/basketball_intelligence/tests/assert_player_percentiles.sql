-- mart_player_percentiles must grade only qualified players, in range, in
-- the right direction. The direction is the easy thing to get backwards
-- (the player with the most turnovers graded best) and every number would
-- still be in range, so the best value in each season is checked to hold
-- the season's top percentile (percent_rank gives tied players the same,
-- slightly under 100 when two share the best value, so 100 itself is not
-- guaranteed). Any row here is a failure.

with graded as (
    select season, player_id, player_name, is_qualified, 'points_per_game' as stat,
           points_per_game as value, points_per_game_pctile as pctile, 'high' as best
    from {{ ref('mart_player_percentiles') }}
    union all
    select season, player_id, player_name, is_qualified, 'turnover_pct',
           turnover_pct, turnover_pct_pctile, 'low'
    from {{ ref('mart_player_percentiles') }}
    union all
    select season, player_id, player_name, is_qualified, 'true_shooting_pct',
           true_shooting_pct, true_shooting_pct_pctile, 'high'
    from {{ ref('mart_player_percentiles') }}
    union all
    select season, player_id, player_name, is_qualified, 'block_pct',
           block_pct, block_pct_pctile, 'high'
    from {{ ref('mart_player_percentiles') }}
),

best_value as (
    select season, stat,
           case when any_value(best) = 'high' then max(value) else min(value) end as best,
           max(pctile) as top_pctile
    from graded
    where is_qualified and value is not null
    group by season, stat
)

-- A percentile outside 0..100
select 'out of range' as problem, season, player_name, stat, pctile as value
from graded
where pctile < 0 or pctile > 100

union all

-- Graded exactly when qualified and the stat has a value
select 'graded mismatch', season, player_name, stat, value
from graded
where (is_qualified and value is not null) <> (pctile is not null)

union all

-- Direction: the best qualified value in a season holds the top percentile,
-- and the percentile never rises as the value gets worse
select 'direction', g.season, g.player_name, g.stat, g.value
from graded g
join best_value b on b.season = g.season and b.stat = g.stat
where g.is_qualified and g.value = b.best and g.pctile < b.top_pctile

union all

select 'monotone', a.season, a.player_name, a.stat, a.value
from graded a
join graded b
  on b.season = a.season and b.stat = a.stat
 and a.is_qualified and b.is_qualified
 and a.value is not null and b.value is not null
 and a.value <> b.value
where ((a.best = 'high' and a.value > b.value) or (a.best = 'low' and a.value < b.value))
  and a.pctile < b.pctile
