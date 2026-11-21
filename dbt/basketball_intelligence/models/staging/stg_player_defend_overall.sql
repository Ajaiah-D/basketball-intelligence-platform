-- One row per player per season, 2013-14 on: every shot he defended as the
-- closest defender (LeagueDashPtDefend, Overall, season totals). Percentages
-- arrive as fractions and are scaled to points. d_fg_pct_diff is how far
-- below (negative) or above those shooters' normal FG% they shot against him.
-- One row per player-season covers every team he played for; a duplicated
-- API row is dropped rather than allowed to break the mart grain.

select
    cast(season as varchar)                  as season,
    cast("CLOSE_DEF_PERSON_ID" as bigint)    as player_id,
    cast("GP" as integer)                    as games_played,
    cast("D_FGM" as double)                  as d_fgm,
    cast("D_FGA" as double)                  as d_fga,
    cast("D_FG_PCT" as double) * 100         as d_fg_pct,
    cast("NORMAL_FG_PCT" as double) * 100    as normal_fg_pct,
    cast("PCT_PLUSMINUS" as double) * 100    as d_fg_pct_diff
from {{ source('raw', 'player_defend_overall') }}
qualify row_number() over (
    partition by season, "CLOSE_DEF_PERSON_ID" order by "D_FGA" desc
) = 1
