-- One row per player per season, 2013-14 on: shots within 6 feet he defended
-- as the closest defender (LeagueDashPtDefend, "Less Than 6Ft", season
-- totals). Percentages scaled to points; rim_fg_pct_diff is the gap to those
-- shooters' normal FG% from that range (negative = he held them below it).

select
    cast(season as varchar)                  as season,
    cast("CLOSE_DEF_PERSON_ID" as bigint)    as player_id,
    cast("FGM_LT_06" as double)              as rim_fgm,
    cast("FGA_LT_06" as double)              as rim_fga,
    cast("LT_06_PCT" as double) * 100        as rim_fg_pct,
    cast("NS_LT_06_PCT" as double) * 100     as rim_normal_fg_pct,
    cast("PLUSMINUS" as double) * 100        as rim_fg_pct_diff
from {{ source('raw', 'player_defend_rim') }}
qualify row_number() over (
    partition by season, "CLOSE_DEF_PERSON_ID" order by "FGA_LT_06" desc
) = 1
