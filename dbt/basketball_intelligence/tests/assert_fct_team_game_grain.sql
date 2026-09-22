-- One row per game, home and away always distinct, and margin must agree
-- with the two point columns it was derived from.
--
-- The last branch is the one that matters most. Uniqueness, the self-join
-- check and the margin arithmetic all still hold on a table whose home and
-- away sides have been swapped wholesale, so none of them can catch an
-- inversion. Checking the home side against the source's own away flag can:
-- for every game the feed orients, the home team must not be the away team.

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

union all

select f.game_id, 'home side is not the vs. team' as problem
from {{ ref('fct_team_game') }} f
join {{ ref('stg_team_game_logs') }} s
  on f.game_id = s.game_id and s.team_id = f.home_team_id
where not f.is_neutral_site and s.is_away_game
