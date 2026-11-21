-- One row per player whose birthdate has been fetched (CommonPlayerInfo, one
-- call per player, cached by ingestion/nba_ingest.py). BIRTHDATE arrives as
-- "1984-12-30T00:00:00". School and country back up the bio index's.

select
    cast("PERSON_ID" as bigint)                                   as player_id,
    try_cast(left(cast("BIRTHDATE" as varchar), 10) as date)      as birthdate,
    nullif(trim(cast("SCHOOL" as varchar)), '')                   as school,
    nullif(trim(cast("COUNTRY" as varchar)), '')                  as country
from {{ source('raw', 'player_birthdates') }}
qualify row_number() over (partition by "PERSON_ID" order by "BIRTHDATE") = 1
