-- mart_player_scoring's shares are shares: each between 0 and 1. The five
-- zone shares add up to 1 (their denominator is the same five zones). The
-- play-type shares add up to at most 1 (a hair over is the rounding of the
-- API's poss_pct, which sets the denominator) and, for a player with 500+
-- possessions, to at least 0.75: the mart keeps only stints where the
-- missing play types (each under 10 possessions) explain what is missing,
-- which can't be a quarter of a big sample. A share over 1 or a sum far off
-- means a traded player's teams, or an incomplete stint, slipped through.

with shares as (
    select
        season,
        player_id,
        zone_fga,
        play_type_possessions,
        [restricted_area_share, paint_share, mid_range_share,
         corner_three_share, above_break_three_share]                 as zone,
        [isolation_share, transition_share, pnr_handler_share, pnr_roll_share,
         post_up_share, spot_up_share, handoff_share, cut_share,
         off_screen_share, putback_share, misc_share]                 as play
    from {{ ref('mart_player_scoring') }}
)

select season, player_id, 'a share outside 0-1' as problem
from shares
where list_min(list_concat(zone, play)) < 0 or list_max(list_concat(zone, play)) > 1

union all

select season, player_id, 'zone shares do not add up to 1'
from shares
where zone_fga > 0 and abs(list_sum(zone) - 1) > 0.001

union all

select season, player_id, 'play-type shares add up to over 1'
from shares
where list_sum(play) > 1.02

union all

select season, player_id, 'play-type shares without play-type possessions'
from shares
where play_type_possessions is null and list_sum(play) is not null

union all

select season, player_id, 'play-type shares of a big sample add up to under 0.75'
from shares
where play_type_possessions >= 500 and list_sum(play) < 0.75
