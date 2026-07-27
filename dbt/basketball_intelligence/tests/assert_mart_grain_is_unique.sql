-- Both marts are one row per entity per season. A duplicate here would
-- silently double-count a player or team on every leaderboard, so fail
-- loudly instead. Written as a singular test to avoid adding a dbt_utils
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
