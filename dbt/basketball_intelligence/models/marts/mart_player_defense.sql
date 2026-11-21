-- One row per player per season: a rough defensive on/off estimate and how
-- often he fouls.
--
-- The NBA publishes no off-court rating without play-by-play lineups, but
-- two published numbers pin it down. The team allowed team_def_rating over
-- all its minutes, and while the player was on the floor it allowed his
-- official defensive_rating, so the minutes he sat must have averaged
--   (team_def_rating - share * on_court) / (1 - share)
-- where share is the part of the team's 48-minute games he played. The
-- gap, on-court minus off-court, is def_on_minus_off: negative means the
-- team defended better with him (lower is better). It is an estimate, not
-- a lineup-based on/off: it leans on rounded published ratings and says
-- nothing about who he played beside.
--
-- The on/off columns are null unless the number can be trusted:
--   - one team all season (team_label has no arrow): a traded player's
--     minutes belong to two team ratings, and team_def_rating is one;
--   - 500+ minutes: a few games make the on-court rating too noisy;
--   - 1996-97 or later: the official rating does not exist before;
--   - share under 0.95: the divisor 1 - share is the minutes he sat, and a
--     player who never sat leaves nothing to estimate from.
-- fouls_per_36 comes from the game logs and is null below 100 minutes, or
-- in a season where any game is missing its foul count. steals_per_36 and
-- blocks_per_36 come from the same game logs under the same 100-minute rule.
--
-- The tracking columns come from the NBA's own player tracking, so they are
-- null before it exists: defender tracking (d_*, rim_*) from 2013-14, hustle
-- stats (*_per_36 other than fouls, steals, blocks) from 2016-17. Hustle
-- rates use the minutes the hustle tracking covers, and are null under 100
-- of them.

with fouls as (
    select
        season,
        player_id,
        count(*) filter (where personal_fouls is null) as games_missing_fouls,
        sum(personal_fouls)                            as personal_fouls,
        sum(steals)                                    as steals,
        sum(blocks)                                    as blocks
    from {{ ref('stg_player_game_logs') }}
    group by season, player_id
),

joined as (
    select
        p.season,
        p.player_id,
        p.player_name,
        p.team_abbreviation,
        p.team_label,
        p.minutes,
        p.games_played,
        p.defensive_rating                           as on_court_def_rating,
        t.defensive_rating                           as team_def_rating,
        t.games_played                               as team_games,
        p.minutes / nullif(t.games_played * 48.0, 0) as minutes_share,
        f.personal_fouls,
        f.games_missing_fouls,
        f.steals,
        f.blocks,
        o.d_fga,
        o.d_fg_pct,
        o.normal_fg_pct,
        o.d_fg_pct_diff,
        r.rim_fga,
        r.rim_fg_pct,
        r.rim_fg_pct_diff,
        h.hustle_minutes,
        h.deflections,
        h.contested_shots,
        h.charges_drawn,
        h.def_loose_balls,
        h.def_box_outs
    from {{ ref('mart_player_season') }} p
    left join {{ ref('mart_team_season') }} t
           on t.season = p.season
          and t.team_abbreviation = p.team_abbreviation
    left join fouls f
           on f.season = p.season
          and f.player_id = p.player_id
    left join {{ ref('stg_player_defend_overall') }} o
           on o.season = p.season
          and o.player_id = p.player_id
    left join {{ ref('stg_player_defend_rim') }} r
           on r.season = p.season
          and r.player_id = p.player_id
    left join {{ ref('stg_player_hustle') }} h
           on h.season = p.season
          and h.player_id = p.player_id
),

-- The null rules, written once.
estimated as (
    select
        *,
        coalesce(
            team_label not like '%→%'
            and minutes >= 500
            and cast(left(season, 4) as int) >= 1996
            and minutes_share < 0.95
            and on_court_def_rating is not null
            and team_def_rating is not null,
            false
        )                                            as has_on_off
    from joined
),

off_court as (
    select
        *,
        case when has_on_off then
            (team_def_rating - minutes_share * on_court_def_rating) / (1 - minutes_share)
        end                                          as est_off_court_def_rating
    from estimated
)

select
    season,
    player_id,
    player_name,
    team_abbreviation,
    minutes,
    games_played,
    on_court_def_rating,
    team_def_rating,
    team_games,
    round(minutes_share, 3)                          as minutes_share,
    round(est_off_court_def_rating, 1)               as est_off_court_def_rating,
    round(on_court_def_rating - est_off_court_def_rating, 1) as def_on_minus_off,
    case when minutes >= 100 and games_missing_fouls = 0 then
        round(36 * personal_fouls / minutes, 2)
    end                                              as fouls_per_36,
    case when minutes >= 100 then round(36 * steals / minutes, 2) end as steals_per_36,
    case when minutes >= 100 then round(36 * blocks / minutes, 2) end as blocks_per_36,

    -- Defender tracking (2013-14 on)
    d_fga,
    round(d_fg_pct, 1)                               as d_fg_pct,
    round(normal_fg_pct, 1)                          as normal_fg_pct,
    round(d_fg_pct_diff, 1)                          as d_fg_pct_diff,
    rim_fga,
    round(rim_fg_pct, 1)                             as rim_fg_pct,
    round(rim_fg_pct_diff, 1)                        as rim_fg_pct_diff,

    -- Hustle stats per 36 tracked minutes (2016-17 on)
    case when hustle_minutes >= 100 then
        round(36 * deflections / hustle_minutes, 2) end     as deflections_per_36,
    case when hustle_minutes >= 100 then
        round(36 * contested_shots / hustle_minutes, 2) end as contested_per_36,
    case when hustle_minutes >= 100 then
        round(36 * charges_drawn / hustle_minutes, 2) end   as charges_per_36,
    case when hustle_minutes >= 100 then
        round(36 * def_loose_balls / hustle_minutes, 2) end as loose_balls_per_36,
    case when hustle_minutes >= 100 then
        round(36 * def_box_outs / hustle_minutes, 2) end    as box_outs_per_36
from off_court
