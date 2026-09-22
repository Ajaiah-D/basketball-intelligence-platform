-- One row per game, home and away always distinct, and margin must agree
-- with the two point columns it was derived from.

select game_id, 'duplicate game' as problem
from {{ ref('fct_team_game') }}
group by game_id
having count(*) > 1

union all

select game_id, 'home equals away' as problem
from {{ ref('fct_team_game') }}
where home_team_id = away_team_id

union all

select game_id, 'margin disagrees with points' as problem
from {{ ref('fct_team_game') }}
where margin <> home_points - away_points
