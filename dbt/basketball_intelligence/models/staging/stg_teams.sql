-- One row per NBA franchise (nba_api static data).

select
    cast(id as bigint)              as team_id,
    cast(full_name as varchar)      as team_name,
    cast(abbreviation as varchar)   as team_abbreviation,
    cast(nickname as varchar)       as team_nickname,
    cast(city as varchar)           as team_city,
    cast(state as varchar)          as team_state,
    cast(year_founded as integer)   as year_founded
from {{ source('raw', 'teams') }}
