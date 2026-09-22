-- One row per player per game. The source records four players under both
-- teams in a single game (identical box scores, different team_id), which
-- double-counts those games in every career total. Written as a singular
-- test to avoid a dbt_utils dependency, matching assert_mart_grain_is_unique.

select
    game_id,
    player_id,
    count(*) as rows
from {{ ref('stg_player_game_logs') }}
group by game_id, player_id
having count(*) > 1
