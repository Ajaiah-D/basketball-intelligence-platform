-- One row per player, all-time index (CommonAllPlayers). Team columns
-- reflect the player's current team and are empty for retired players.

select
    cast(person_id as bigint)               as player_id,
    cast(display_first_last as varchar)     as player_name,
    cast(display_last_comma_first as varchar) as player_name_last_first,
    cast(player_slug as varchar)            as player_slug,
    cast(rosterstatus as integer) = 1       as is_active,
    cast(from_year as integer)              as first_season_year,
    cast(to_year as integer)                as last_season_year,
    nullif(cast(team_id as bigint), 0)      as team_id,
    nullif(cast(team_city as varchar), '')  as team_city,
    nullif(cast(team_name as varchar), '')  as team_name,
    nullif(cast(team_abbreviation as varchar), '') as team_abbreviation,
    cast(games_played_flag as varchar) = 'Y' as has_played_games
from {{ source('raw', 'players') }}
