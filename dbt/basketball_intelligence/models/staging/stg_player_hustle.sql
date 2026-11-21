-- One row per player per season, 2016-17 on: hustle stats as season totals
-- (LeagueHustleStatsPlayer). hustle_minutes is the minutes the tracking
-- covers, the denominator for the per-36 rates in mart_player_defense.

select
    cast(season as varchar)                        as season,
    cast("PLAYER_ID" as bigint)                    as player_id,
    cast("MIN" as double)                          as hustle_minutes,
    cast("DEFLECTIONS" as double)                  as deflections,
    cast("CONTESTED_SHOTS" as double)              as contested_shots,
    cast("CHARGES_DRAWN" as double)                as charges_drawn,
    cast("DEF_LOOSE_BALLS_RECOVERED" as double)    as def_loose_balls,
    cast("DEF_BOXOUTS" as double)                  as def_box_outs
from {{ source('raw', 'player_hustle') }}
qualify row_number() over (partition by season, "PLAYER_ID" order by "MIN" desc) = 1
