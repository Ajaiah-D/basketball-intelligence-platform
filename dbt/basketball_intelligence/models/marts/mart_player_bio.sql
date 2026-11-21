-- One row per player ever: what the Player tab's bio line and the All
-- players position filter show. The bio index (PlayerIndex) is the main
-- source; the per-player CommonPlayerInfo cache adds the birthdate and fills
-- a missing college or country. A null draft_year means undrafted.

select
    b.player_id,
    b.position,
    b.height,
    case when b.height like '%-%' then
        try_cast(split_part(b.height, '-', 1) as integer) * 12
        + try_cast(split_part(b.height, '-', 2) as integer)
    end                                       as height_inches,
    b.weight,
    d.birthdate,
    coalesce(b.country, d.country)            as country,
    coalesce(b.college, d.school)             as college,
    b.draft_year,
    b.draft_round,
    b.draft_number,
    coalesce(p.is_active, false)              as is_active
from {{ ref('stg_player_bio') }} b
left join {{ ref('stg_player_birthdates') }} d on d.player_id = b.player_id
left join {{ ref('stg_players') }} p on p.player_id = b.player_id
