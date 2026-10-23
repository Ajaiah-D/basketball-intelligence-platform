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
-- in a season where any game is missing its foul count.

with fouls as (
    select
        season,
        player_id,
        count(*) filter (where personal_fouls is null) as games_missing_fouls,
        sum(personal_fouls)                            as personal_fouls
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
        f.games_missing_fouls
    from {{ ref('mart_player_season') }} p
    left join {{ ref('mart_team_season') }} t
           on t.season = p.season
          and t.team_abbreviation = p.team_abbreviation
    left join fouls f
           on f.season = p.season
          and f.player_id = p.player_id
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
    end                                              as fouls_per_36
from off_court
