-- mart_player_defense's on/off columns must be null exactly when the rules
-- in the model say so, and the arithmetic must hold where they are not.
-- The rules are restated here from the inputs (mart_player_season and
-- mart_team_season), not from the model's own helper flag, so a slip in
-- the flag shows up. Any row here is a failure.

with expected as (
    select
        d.season,
        d.player_id,
        d.player_name,
        d.def_on_minus_off,
        d.est_off_court_def_rating,
        d.on_court_def_rating,
        d.team_def_rating,
        d.minutes_share,
        d.fouls_per_36,
        d.minutes,
        (s.team_label not like '%→%'
         and s.minutes >= 500
         and cast(left(s.season, 4) as int) >= 1996
         and s.minutes / (t.games_played * 48.0) < 0.95
         and s.defensive_rating is not null
         and t.defensive_rating is not null) as should_have_on_off
    from {{ ref('mart_player_defense') }} d
    join {{ ref('mart_player_season') }} s
      on s.season = d.season and s.player_id = d.player_id
    left join {{ ref('mart_team_season') }} t
      on t.season = s.season and t.team_abbreviation = s.team_abbreviation
)

-- On/off present when the rules say no, or missing when they say yes
select 'on/off null mismatch' as problem, season, player_name, def_on_minus_off as value
from expected
where coalesce(should_have_on_off, false) <> (def_on_minus_off is not null)
   or (def_on_minus_off is null) <> (est_off_court_def_rating is null)

union all

-- The estimate must reproduce the team rating when weighted back by the
-- minutes share: share x on + (1 - share) x off = team (rounding slack
-- from the 3-decimal share and 1-decimal off-court rating)
select 'does not average back to the team rating', season, player_name,
       minutes_share * on_court_def_rating
         + (1 - minutes_share) * est_off_court_def_rating - team_def_rating
from expected
where def_on_minus_off is not null
  and abs(minutes_share * on_court_def_rating
        + (1 - minutes_share) * est_off_court_def_rating - team_def_rating) > 0.5

union all

-- The gap is on-court minus off-court, so negative is a better defense
-- (the sign is the easy thing to flip; the rounded inputs allow 0.15)
select 'wrong sign or size', season, player_name, def_on_minus_off
from expected
where def_on_minus_off is not null
  and abs(def_on_minus_off - (on_court_def_rating - est_off_court_def_rating)) > 0.15

union all

-- Fouls: null below 100 minutes, otherwise a believable rate
select 'fouls_per_36 out of range', season, player_name, fouls_per_36
from expected
where fouls_per_36 is not null and (fouls_per_36 < 0 or fouls_per_36 > 15)

union all

select 'fouls_per_36 null mismatch', season, player_name, fouls_per_36
from expected
where minutes < 100 and fouls_per_36 is not null
