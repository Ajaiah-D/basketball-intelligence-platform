-- mart_player_defense's on/off columns must come from the source the rules
-- in the model pick, be null exactly when neither applies, and the
-- arithmetic must hold where they are not. The rules are restated here
-- from the inputs (mart_player_season, mart_team_season and
-- stg_player_on_off), not from the model's own columns, so a slip in the
-- model shows up. Any row here is a failure.

with official as (
    select
        season,
        player_id,
        sum(on_minutes * on_def_rating) / sum(on_minutes) as on_rating
    from {{ ref('stg_player_on_off') }}
    where on_minutes > 0
      and off_minutes > 0
      and on_def_rating is not null
      and off_def_rating is not null
    group by season, player_id
),

expected as (
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
        d.on_off_source,
        o.on_rating                                as official_on_rating,
        case
            when s.minutes >= 500 and o.player_id is not null then 'official'
            when s.team_label not like '%→%'
             and s.minutes >= 500
             and cast(left(s.season, 4) as int) >= 1996
             and s.minutes / (t.games_played * 48.0) < 0.95
             and s.defensive_rating is not null
             and t.defensive_rating is not null then 'estimate'
        end                                        as should_source
    from {{ ref('mart_player_defense') }} d
    join {{ ref('mart_player_season') }} s
      on s.season = d.season and s.player_id = d.player_id
    left join {{ ref('mart_team_season') }} t
      on t.season = s.season and t.team_abbreviation = s.team_abbreviation
    left join official o
      on o.season = d.season and o.player_id = d.player_id
)

-- The source the rules pick, and on/off present exactly when there is one
select 'on/off source mismatch' as problem, season, player_name, def_on_minus_off as value
from expected
where coalesce(should_source, '-') <> coalesce(on_off_source, '-')
   or (def_on_minus_off is null) <> (on_off_source is null)
   or (def_on_minus_off is null) <> (est_off_court_def_rating is null)

union all

-- The estimate must reproduce the team rating when weighted back by the
-- minutes share: share x on + (1 - share) x off = team (rounding slack
-- from the 3-decimal share and 1-decimal off-court rating)
select 'does not average back to the team rating', season, player_name,
       minutes_share * on_court_def_rating
         + (1 - minutes_share) * est_off_court_def_rating - team_def_rating
from expected
where on_off_source = 'estimate'
  and abs(minutes_share * on_court_def_rating
        + (1 - minutes_share) * est_off_court_def_rating - team_def_rating) > 0.5

union all

-- The gap is on-court minus off-court, so negative is a better defense
-- (the sign is the easy thing to flip; the rounded inputs allow 0.15).
-- The on-court side is the official rating for estimate rows and the NBA's
-- minutes-weighted on-court rating for official rows.
select 'wrong sign or size', season, player_name, def_on_minus_off
from expected
where on_off_source is not null
  and abs(def_on_minus_off
          - (case on_off_source when 'official' then official_on_rating
                                else on_court_def_rating end
             - est_off_court_def_rating)) > 0.15

union all

-- An official gap past 30 points per 100 possessions over 500+ minutes
-- means the on and off rows were mixed up
select 'official on/off out of range', season, player_name, def_on_minus_off
from expected
where on_off_source = 'official' and abs(def_on_minus_off) > 30

union all

-- Fouls: null below 100 minutes, otherwise a believable rate
select 'fouls_per_36 out of range', season, player_name, fouls_per_36
from expected
where fouls_per_36 is not null and (fouls_per_36 < 0 or fouls_per_36 > 15)

union all

select 'fouls_per_36 null mismatch', season, player_name, fouls_per_36
from expected
where minutes < 100 and fouls_per_36 is not null
