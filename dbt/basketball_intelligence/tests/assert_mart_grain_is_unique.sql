-- All four marts here are one row per entity per season. A duplicate would
-- silently double-count a player or team on every leaderboard (or double a
-- team's win-loss record in the standings, or its payroll), so fail loudly
-- instead. Written as a singular test to avoid adding a dbt_utils
-- dependency for one assertion.

select 'mart_player_season' as model, season, cast(player_id as varchar) as entity, count(*) as rows
from {{ ref('mart_player_season') }}
group by season, player_id
having count(*) > 1

union all

select 'mart_team_season' as model, season, cast(team_id as varchar) as entity, count(*) as rows
from {{ ref('mart_team_season') }}
group by season, team_id
having count(*) > 1

union all

select 'mart_team_standings' as model, season, cast(team_id as varchar) as entity, count(*) as rows
from {{ ref('mart_team_standings') }}
group by season, team_id
having count(*) > 1

union all

select 'mart_team_finances' as model, season, cast(team_abbreviation as varchar) as entity, count(*) as rows
from {{ ref('mart_team_finances') }}
group by season, team_abbreviation
having count(*) > 1
