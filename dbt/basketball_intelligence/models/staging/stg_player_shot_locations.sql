-- One row per player per season, 1996-97 on: field goal attempts by zone as
-- season totals (LeagueDashPlayerShotLocations, "By Zone"). The API already
-- adds a traded player's teams up. A zone he never shot from comes back
-- null, so it is 0 here. Backcourt heaves are kept apart: they say nothing
-- about how he plays.

select
    cast(season as varchar)                                   as season,
    cast("PLAYER_ID" as bigint)                               as player_id,
    coalesce(cast("RESTRICTED_AREA_FGA" as double), 0)        as restricted_area_fga,
    coalesce(cast("IN_THE_PAINT_NON_RA_FGA" as double), 0)    as paint_fga,
    coalesce(cast("MID_RANGE_FGA" as double), 0)              as mid_range_fga,
    coalesce(cast("CORNER_3_FGA" as double), 0)               as corner_three_fga,
    coalesce(cast("ABOVE_THE_BREAK_3_FGA" as double), 0)      as above_break_three_fga,
    coalesce(cast("BACKCOURT_FGA" as double), 0)              as backcourt_fga
from {{ source('raw', 'player_shot_locations') }}
qualify row_number() over (
    partition by season, "PLAYER_ID"
    order by coalesce(cast("RESTRICTED_AREA_FGA" as double), 0) desc
) = 1
