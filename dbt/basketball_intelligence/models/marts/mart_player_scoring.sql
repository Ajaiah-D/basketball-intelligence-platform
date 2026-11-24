-- One row per player per season: how he gets his shots. Two parts, each
-- null in seasons its source doesn't cover:
--
-- Shot diet (1996-97 on, stg_player_shot_locations): the share of his field
-- goal attempts from each zone. The denominator is the five half-court
-- zones, so the shares add up to 1; backcourt heaves are left out.
--
-- Play types (2015-16 on, stg_player_play_types): the share of his offensive
-- possessions in each Synergy play type. The API lists only play types with
-- 10+ possessions for a team, and a traded player once per team. So his
-- possessions with a team come from the API's own share (possessions /
-- poss_pct, taken from his biggest play type there, where the rounding of
-- poss_pct matters least), the teams are added up, and each play type's
-- possessions over that total is its share. A play type he used under 10
-- times for a team counts as 0, so the shares add up to a little under 1.
--
-- Some answers are missing rows the API should have: in 2023-24 whole play
-- types are gone for many players (Malik Beasley's 316 spot-ups among
-- them), and in later seasons some traded players' stints keep only a few
-- play types. Asking again returns the same rows. A missing play type under
-- 10 possessions explains at most 9 of them, so a stint whose possessions
-- exceed what its rows hold by more than 9 per missing play type (plus 2%
-- for the rounding of poss_pct) is incomplete, and is left out. A player
-- with no complete stint has null play types.

with zones as (
    select
        season,
        player_id,
        restricted_area_fga + paint_fga + mid_range_fga
            + corner_three_fga + above_break_three_fga  as zone_fga,
        restricted_area_fga,
        paint_fga,
        mid_range_fga,
        corner_three_fga,
        above_break_three_fga
    from {{ ref('stg_player_shot_locations') }}
),

stints as (
    select
        season,
        player_id,
        team_id,
        arg_max(possessions / poss_pct, possessions) as stint_possessions,
        sum(possessions)                              as listed_possessions,
        count(*)                                      as play_types_listed
    from {{ ref('stg_player_play_types') }}
    where poss_pct > 0
    group by season, player_id, team_id
),

complete_stints as (
    select season, player_id, team_id, stint_possessions
    from stints
    where stint_possessions - listed_possessions
        <= 9 * (11 - play_types_listed) + 0.02 * stint_possessions
),

play_totals as (
    select season, player_id, sum(stint_possessions) as play_type_possessions
    from complete_stints
    group by season, player_id
),

play_types as (
    -- Capped at 1: the estimated total can round a hair under one play
    -- type's own count when a single play type is nearly all he did.
    select
        p.season,
        p.player_id,
        t.play_type_possessions,
        least(sum(case when p.play_type = 'isolation' then p.possessions else 0 end)
            / t.play_type_possessions, 1) as isolation_share,
        least(sum(case when p.play_type = 'transition' then p.possessions else 0 end)
            / t.play_type_possessions, 1) as transition_share,
        least(sum(case when p.play_type = 'prballhandler' then p.possessions else 0 end)
            / t.play_type_possessions, 1) as pnr_handler_share,
        least(sum(case when p.play_type = 'prrollman' then p.possessions else 0 end)
            / t.play_type_possessions, 1) as pnr_roll_share,
        least(sum(case when p.play_type = 'postup' then p.possessions else 0 end)
            / t.play_type_possessions, 1) as post_up_share,
        least(sum(case when p.play_type = 'spotup' then p.possessions else 0 end)
            / t.play_type_possessions, 1) as spot_up_share,
        least(sum(case when p.play_type = 'handoff' then p.possessions else 0 end)
            / t.play_type_possessions, 1) as handoff_share,
        least(sum(case when p.play_type = 'cut' then p.possessions else 0 end)
            / t.play_type_possessions, 1) as cut_share,
        least(sum(case when p.play_type = 'offscreen' then p.possessions else 0 end)
            / t.play_type_possessions, 1) as off_screen_share,
        least(sum(case when p.play_type = 'offrebound' then p.possessions else 0 end)
            / t.play_type_possessions, 1) as putback_share,
        least(sum(case when p.play_type = 'misc' then p.possessions else 0 end)
            / t.play_type_possessions, 1) as misc_share
    from {{ ref('stg_player_play_types') }} p
    join complete_stints c
        on c.season = p.season and c.player_id = p.player_id and c.team_id = p.team_id
    join play_totals t on t.season = p.season and t.player_id = p.player_id
    group by p.season, p.player_id, t.play_type_possessions
),

players as (
    select season, player_id from zones
    union
    select season, player_id from play_types
)

select
    k.season,
    k.player_id,
    z.zone_fga,
    z.restricted_area_fga / nullif(z.zone_fga, 0)    as restricted_area_share,
    z.paint_fga / nullif(z.zone_fga, 0)              as paint_share,
    z.mid_range_fga / nullif(z.zone_fga, 0)          as mid_range_share,
    z.corner_three_fga / nullif(z.zone_fga, 0)       as corner_three_share,
    z.above_break_three_fga / nullif(z.zone_fga, 0)  as above_break_three_share,
    p.play_type_possessions,
    p.isolation_share,
    p.transition_share,
    p.pnr_handler_share,
    p.pnr_roll_share,
    p.post_up_share,
    p.spot_up_share,
    p.handoff_share,
    p.cut_share,
    p.off_screen_share,
    p.putback_share,
    p.misc_share
from players k
left join zones z on z.season = k.season and z.player_id = k.player_id
left join play_types p on p.season = k.season and p.player_id = k.player_id
