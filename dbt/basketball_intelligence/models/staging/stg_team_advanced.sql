-- One row per team per season. Official NBA advanced team stats
-- (LeagueDashTeamStats, Advanced measure type), 1996-97 onward.

select
    cast(season as varchar)              as season,
    cast("TEAM_ID" as bigint)            as team_id,
    cast("TEAM_NAME" as varchar)         as team_name,
    cast("GP" as integer)                as games_played,
    cast("W" as integer)                 as wins,
    cast("L" as integer)                 as losses,
    cast("OFF_RATING" as double)         as offensive_rating,
    cast("DEF_RATING" as double)         as defensive_rating,
    cast("NET_RATING" as double)         as net_rating,
    cast("AST_PCT" as double) * 100      as assist_pct,
    cast("OREB_PCT" as double) * 100     as offensive_rebound_pct,
    cast("DREB_PCT" as double) * 100     as defensive_rebound_pct,
    cast("REB_PCT" as double) * 100      as rebound_pct,
    cast("TM_TOV_PCT" as double) * 100   as turnover_pct,
    cast("EFG_PCT" as double) * 100      as effective_fg_pct,
    cast("TS_PCT" as double) * 100       as true_shooting_pct,
    cast("PACE" as double)               as pace
from {{ source('raw', 'team_advanced') }}
