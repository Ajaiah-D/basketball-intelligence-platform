-- Two things about mart_team_standings that must always hold:
--
-- 1. wins + losses = games_played for every row - a team can't have
--    unaccounted games, and this would catch a join that dropped or
--    duplicated a game.
--
-- 2. The (win_pct, net_points, head_to_head) ordering key never leaves two
--    teams in the same season and conference genuinely indistinguishable.
--    head_to_head is documented as a simplification - it does not resolve
--    every possible tie the way the NBA's full rulebook does - but the
--    model's own final sort column, team_abbreviation, is unique per team
--    by construction and must always be present to break whatever the
--    first three keys don't. This fails only if that fallback itself goes
--    missing or stops being unique (a grain violation, or a future edit
--    that drops the final ORDER BY column), which is exactly the case
--    where standings order would stop being deterministic across reruns.

select season, team_abbreviation, 'wins + losses <> games_played' as problem
from {{ ref('mart_team_standings') }}
where wins + losses <> games_played

union all

select
    season,
    string_agg(coalesce(team_abbreviation, '<null>'), ', ' order by team_abbreviation),
    'tied on win_pct, net_points, head_to_head with no deterministic fallback' as problem
from {{ ref('mart_team_standings') }}
group by season, conference, win_pct, net_points, head_to_head
having count(*) > count(distinct team_abbreviation)
    or count(*) filter (where team_abbreviation is null) > 0
