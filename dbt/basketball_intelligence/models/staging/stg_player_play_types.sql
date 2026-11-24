-- One row per player, team, season and play type, 2015-16 on: offensive
-- possessions by Synergy play type as season totals (SynergyPlayTypes).
-- The API lists a player only in play types where he had 10 or more
-- possessions, and a traded player once per team (mart_player_scoring adds
-- the teams up). poss_pct is the play type's share of his possessions with
-- that team, rounded to three places.

select
    cast(season as varchar)              as season,
    cast("PLAYER_ID" as bigint)          as player_id,
    cast("TEAM_ID" as bigint)            as team_id,
    -- Lower-cased: the API answers "PRRollMan" to a request for "PRRollman".
    lower(cast("PLAY_TYPE" as varchar))  as play_type,
    cast("POSS" as double)               as possessions,
    cast("POSS_PCT" as double)           as poss_pct
from {{ source('raw', 'player_play_types') }}
qualify row_number() over (
    partition by season, "PLAYER_ID", "TEAM_ID", "PLAY_TYPE" order by "POSS" desc
) = 1
