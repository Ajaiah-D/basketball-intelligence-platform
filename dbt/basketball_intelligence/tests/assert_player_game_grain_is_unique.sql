-- One row per player per game. The source records four players under both
-- teams in a single game (identical box scores, different team_id), which
-- double-counts those games in every career total. Written as a singular
-- test to avoid a dbt_utils dependency, matching assert_mart_grain_is_unique.
-- mart_player_game is checked too: its join to the team logs would repeat a
-- game if a team ever logged it twice.

select
    'stg_player_game_logs' as model,
    game_id,
    player_id,
    count(*) as rows
from {{ ref('stg_player_game_logs') }}
group by game_id, player_id
having count(*) > 1

union all

select
    'mart_player_game' as model,
    game_id,
    player_id,
    count(*) as rows
from {{ ref('mart_player_game') }}
group by game_id, player_id
having count(*) > 1
