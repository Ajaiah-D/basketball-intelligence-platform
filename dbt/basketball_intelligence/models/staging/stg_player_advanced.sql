-- One row per player per season. Official NBA advanced stats
-- (LeagueDashPlayerStats, Advanced measure type), 1996-97 onward.
-- Percentages arrive as fractions (0.612) and are scaled to points here so
-- they match the box-score-derived percentages elsewhere in the warehouse.

select
    cast(season as varchar)             as season,
    cast("PLAYER_ID" as bigint)         as player_id,
    cast("PLAYER_NAME" as varchar)      as player_name,
    cast("TEAM_ABBREVIATION" as varchar) as team_abbreviation,
    cast("GP" as integer)               as games_played,
    cast("MIN" as double)               as minutes_per_game,
    cast("OFF_RATING" as double)        as offensive_rating,
    cast("DEF_RATING" as double)        as defensive_rating,
    cast("NET_RATING" as double)        as net_rating,
    cast("AST_PCT" as double) * 100     as assist_pct,
    cast("AST_TO" as double)            as assist_to_turnover,
    cast("OREB_PCT" as double) * 100    as offensive_rebound_pct,
    cast("DREB_PCT" as double) * 100    as defensive_rebound_pct,
    cast("REB_PCT" as double) * 100     as rebound_pct,
    cast("TM_TOV_PCT" as double) * 100  as turnover_pct,
    cast("EFG_PCT" as double) * 100     as effective_fg_pct,
    cast("TS_PCT" as double) * 100      as true_shooting_pct,
    cast("USG_PCT" as double) * 100     as usage_pct,
    cast("PACE" as double)              as pace,
    cast("PIE" as double) * 100         as player_impact_estimate
from {{ source('raw', 'player_advanced') }}
