-- One row per player, team and season, 2007-08 on: the team's defensive
-- rating with him on the floor and off it (TeamPlayerOnOffSummary, season
-- totals). Lineup-based, from the NBA's own play-by-play. A traded player
-- has a row for each team he played for. mart_player_defense combines them.

with rows as (
    select
        cast(season as varchar)              as season,
        cast("TEAM_ID" as bigint)            as team_id,
        cast("TEAM_ABBREVIATION" as varchar) as team_abbreviation,
        cast("VS_PLAYER_ID" as bigint)       as player_id,
        cast("COURT_STATUS" as varchar)      as court_status,
        cast("MIN" as double)                as minutes,
        cast("DEF_RATING" as double)         as def_rating
    from {{ source('raw', 'player_on_off') }}
    qualify row_number() over (
        partition by season, "TEAM_ID", "VS_PLAYER_ID", "COURT_STATUS" order by "MIN" desc
    ) = 1
)

select
    n.season,
    n.team_id,
    n.team_abbreviation,
    n.player_id,
    n.minutes          as on_minutes,
    n.def_rating       as on_def_rating,
    f.minutes          as off_minutes,
    f.def_rating       as off_def_rating
from rows n
join rows f
  on f.season = n.season
 and f.team_id = n.team_id
 and f.player_id = n.player_id
 and f.court_status = 'Off'
where n.court_status = 'On'
