-- One row per play-by-play event (PlayByPlayV3). Renames camelCase API
-- fields to snake_case and types them. teamId/personId of 0 mean the
-- event has no team/player (e.g. period start) and are nulled out.

select
    cast("gameId" as varchar)               as game_id,
    cast(season as varchar)                 as season,
    cast("actionNumber" as integer)         as action_number,
    cast("actionId" as integer)             as action_id,
    cast(period as integer)                 as period,
    cast(clock as varchar)                  as game_clock,  -- ISO-8601 duration, e.g. PT11M22.00S
    nullif(cast("teamId" as bigint), 0)     as team_id,
    nullif(cast("teamTricode" as varchar), '') as team_tricode,
    nullif(cast("personId" as bigint), 0)   as player_id,
    nullif(cast("playerName" as varchar), '') as player_name,
    cast("actionType" as varchar)           as action_type,
    cast("subType" as varchar)              as action_subtype,
    cast(description as varchar)            as description,
    cast("isFieldGoal" as integer) = 1      as is_field_goal,
    nullif(cast("shotResult" as varchar), '') as shot_result,
    cast("shotDistance" as integer)         as shot_distance_ft,
    cast("shotValue" as integer)            as shot_value,
    cast("xLegacy" as integer)              as shot_x,
    cast("yLegacy" as integer)              as shot_y,
    try_cast("scoreHome" as integer)        as score_home,
    try_cast("scoreAway" as integer)        as score_away,
    cast("pointsTotal" as integer)          as player_points_total,
    nullif(cast(location as varchar), '')   as location
from {{ source('raw', 'play_by_play') }}
