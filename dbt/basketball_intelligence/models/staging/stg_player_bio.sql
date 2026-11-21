-- One row per player, every player ever (PlayerIndex, historical): the NBA's
-- position label (G, F, C, G-F, F-C ...), height as feet-inches ("6-6"),
-- weight in pounds, college, country and draft. Blanks become null; a
-- player with no draft year was undrafted.

select
    cast("PERSON_ID" as bigint)                      as player_id,
    nullif(trim(cast("POSITION" as varchar)), '')    as position,
    nullif(trim(cast("HEIGHT" as varchar)), '')      as height,
    try_cast("WEIGHT" as integer)                    as weight,
    nullif(trim(cast("COLLEGE" as varchar)), '')     as college,
    nullif(trim(cast("COUNTRY" as varchar)), '')     as country,
    try_cast("DRAFT_YEAR" as integer)                as draft_year,
    try_cast("DRAFT_ROUND" as integer)               as draft_round,
    try_cast("DRAFT_NUMBER" as integer)              as draft_number
from {{ source('raw', 'player_bio') }}
qualify row_number() over (partition by "PERSON_ID" order by "TO_YEAR" desc) = 1
