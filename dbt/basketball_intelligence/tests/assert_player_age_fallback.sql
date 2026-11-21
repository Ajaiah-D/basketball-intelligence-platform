-- mart_player_season.age takes the NBA's published age first, then the age
-- worked out from the birthdate, then the count back from a later season.
-- Returns a row (fails) when:
--   - a season with an NBA-published age shows a different age, or
--   - an age is outside 17-45, which only a wrong birthdate or a broken
--     February-1 rule would produce.

select
    s.season,
    s.player_id,
    s.age,
    a.age as nba_age
from {{ ref('mart_player_season') }} s
left join {{ ref('stg_player_advanced') }} a
       on a.season = s.season
      and a.player_id = s.player_id
where (a.age is not null and s.age <> cast(floor(a.age) as int))
   or s.age not between 17 and 45
