-- One row per player per season with advanced rate metrics derived from
-- box scores, so all 47 ingested seasons are covered (the NBA only
-- publishes official advanced stats from 1996-97). Official figures are
-- joined on where they exist so the derived ones can be checked.
--
-- Team context is summed over exactly the games the player appeared in,
-- which keeps mid-season trades honest instead of attributing a player's
-- rates to whichever team he finished the year with.
--
-- Rate formulas follow the standard public definitions (Basketball
-- Reference); "team game minutes" below is team minutes / 5, i.e. the
-- minutes of game time the team played.

with player_games as (
    select
        p.season,
        p.player_id,
        p.player_name,
        p.team_abbreviation,
        p.game_date,
        p.minutes_played,
        p.points,
        p.field_goals_made,
        p.field_goals_attempted,
        p.three_pointers_made,
        p.three_pointers_attempted,
        p.free_throws_made,
        p.free_throws_attempted,
        p.offensive_rebounds,
        p.defensive_rebounds,
        p.total_rebounds,
        p.assists,
        p.steals,
        p.blocks,
        p.turnovers,
        p.personal_fouls,
        p.plus_minus,
        t.minutes_played           as team_minutes,
        t.field_goals_made         as team_field_goals_made,
        t.field_goals_attempted    as team_field_goals_attempted,
        t.free_throws_attempted    as team_free_throws_attempted,
        t.offensive_rebounds       as team_offensive_rebounds,
        t.defensive_rebounds       as team_defensive_rebounds,
        t.total_rebounds           as team_total_rebounds,
        t.turnovers                as team_turnovers,
        o.field_goals_attempted    as opp_field_goals_attempted,
        o.three_pointers_attempted as opp_three_pointers_attempted,
        o.free_throws_attempted    as opp_free_throws_attempted,
        o.offensive_rebounds       as opp_offensive_rebounds,
        o.defensive_rebounds       as opp_defensive_rebounds,
        o.total_rebounds           as opp_total_rebounds,
        o.turnovers                as opp_turnovers
    from {{ ref('stg_player_game_logs') }} p
    join {{ ref('stg_team_game_logs') }} t
      on p.game_id = t.game_id
     and p.team_id = t.team_id
    join {{ ref('stg_team_game_logs') }} o
      on p.game_id = o.game_id
     and p.team_id <> o.team_id
),

totals as (
    select
        season,
        player_id,
        any_value(player_name)                as player_name,
        max_by(team_abbreviation, game_date)  as team_abbreviation,
        count(*)                              as games_played,
        -- Box scores are only complete from 1985-86; before that whole
        -- columns are missing (1979-80 has no field goal attempts, rebounds
        -- or assists at all). sum() skips nulls silently, so a partial
        -- season would produce a confident wrong answer rather than none.
        -- Any missing input withholds the season's derived metrics.
        count(*) filter (
            where field_goals_attempted is null
               or three_pointers_attempted is null
               or offensive_rebounds is null
               or defensive_rebounds is null
               or total_rebounds is null
               or assists is null
               or steals is null
               or blocks is null
               or turnovers is null
               or team_field_goals_attempted is null
               or team_offensive_rebounds is null
               or team_total_rebounds is null
               or team_turnovers is null
               or opp_field_goals_attempted is null
               or opp_three_pointers_attempted is null
               or opp_offensive_rebounds is null
               or opp_defensive_rebounds is null
               or opp_total_rebounds is null
               or opp_turnovers is null
        )                                     as incomplete_games,
        sum(minutes_played)                   as minutes,
        sum(points)                           as points,
        sum(field_goals_made)                 as field_goals_made,
        sum(field_goals_attempted)            as field_goals_attempted,
        sum(three_pointers_made)              as three_pointers_made,
        sum(three_pointers_attempted)         as three_pointers_attempted,
        sum(free_throws_made)                 as free_throws_made,
        sum(free_throws_attempted)            as free_throws_attempted,
        sum(offensive_rebounds)               as offensive_rebounds,
        sum(defensive_rebounds)               as defensive_rebounds,
        sum(total_rebounds)                   as total_rebounds,
        sum(assists)                          as assists,
        sum(steals)                           as steals,
        sum(blocks)                           as blocks,
        sum(turnovers)                        as turnovers,
        sum(personal_fouls)                   as personal_fouls,
        avg(plus_minus)                       as plus_minus_per_game,
        -- Team and opponent context over the player's games only
        sum(team_minutes) / 5.0               as team_game_minutes,
        sum(team_field_goals_made)            as team_field_goals_made,
        sum(team_field_goals_attempted)       as team_field_goals_attempted,
        sum(team_free_throws_attempted)       as team_free_throws_attempted,
        sum(team_offensive_rebounds)          as team_offensive_rebounds,
        sum(team_defensive_rebounds)          as team_defensive_rebounds,
        sum(team_total_rebounds)              as team_total_rebounds,
        sum(team_turnovers)                   as team_turnovers,
        sum(opp_field_goals_attempted)        as opp_field_goals_attempted,
        sum(opp_three_pointers_attempted)     as opp_three_pointers_attempted,
        sum(opp_free_throws_attempted)        as opp_free_throws_attempted,
        sum(opp_offensive_rebounds)           as opp_offensive_rebounds,
        sum(opp_defensive_rebounds)           as opp_defensive_rebounds,
        sum(opp_total_rebounds)               as opp_total_rebounds,
        sum(opp_turnovers)                    as opp_turnovers
    from player_games
    group by season, player_id
),

derived as (
    select
        *,
        incomplete_games = 0                           as box_score_complete,
        case when incomplete_games > 0 then null else
            team_field_goals_attempted + 0.44 * team_free_throws_attempted
                - team_offensive_rebounds + team_turnovers end as team_possessions,
        case when incomplete_games > 0 then null else
            opp_field_goals_attempted + 0.44 * opp_free_throws_attempted
                - opp_offensive_rebounds + opp_turnovers end   as opp_possessions,
        -- Share of the team's floor time this player was on for
        minutes / nullif(team_game_minutes, 0)         as minutes_share
    from totals
)

select
    d.season,
    d.player_id,
    d.player_name,
    d.team_abbreviation,
    d.games_played,
    d.minutes,
    round(d.minutes / nullif(d.games_played, 0), 1)    as minutes_per_game,
    round(d.points / nullif(d.games_played, 0), 1)     as points_per_game,

    -- Shooting efficiency
    case when d.box_score_complete then
        round(100 * d.points / nullif(2 * (d.field_goals_attempted
            + 0.44 * d.free_throws_attempted), 0), 1) end as true_shooting_pct,
    case when d.box_score_complete then
        round(100 * (d.field_goals_made + 0.5 * d.three_pointers_made)
            / nullif(d.field_goals_attempted, 0), 1) end  as effective_fg_pct,
    case when d.box_score_complete then
        round(d.three_pointers_attempted
            / nullif(d.field_goals_attempted, 0), 3) end  as three_point_attempt_rate,
    case when d.box_score_complete then
        round(d.free_throws_attempted
            / nullif(d.field_goals_attempted, 0), 3) end  as free_throw_rate,

    -- Involvement and role
    coalesce(a.usage_pct, case when d.box_score_complete then
        round(100 * ((d.field_goals_attempted + 0.44 * d.free_throws_attempted
            + d.turnovers) * d.team_game_minutes)
            / nullif(d.minutes * (d.team_field_goals_attempted
            + 0.44 * d.team_free_throws_attempted + d.team_turnovers), 0), 1) end) as usage_pct,
    case when d.box_score_complete then
        round(100 * d.assists / nullif(d.minutes_share * d.team_field_goals_made
            - d.field_goals_made, 0), 1) end           as assist_pct,
    case when d.box_score_complete then
        round(100 * d.turnovers / nullif(d.field_goals_attempted
            + 0.44 * d.free_throws_attempted + d.turnovers, 0), 1) end as turnover_pct,

    -- Rebounding and defensive rates
    case when d.box_score_complete then
        round(100 * (d.total_rebounds * d.team_game_minutes)
            / nullif(d.minutes * (d.team_total_rebounds
            + d.opp_total_rebounds), 0), 1) end        as rebound_pct,
    case when d.box_score_complete then
        round(100 * (d.offensive_rebounds * d.team_game_minutes)
            / nullif(d.minutes * (d.team_offensive_rebounds
            + d.opp_defensive_rebounds), 0), 1) end    as offensive_rebound_pct,
    case when d.box_score_complete then
        round(100 * (d.defensive_rebounds * d.team_game_minutes)
            / nullif(d.minutes * (d.team_defensive_rebounds
            + d.opp_offensive_rebounds), 0), 1) end    as defensive_rebound_pct,
    case when d.box_score_complete then
        round(100 * (d.steals * d.team_game_minutes)
            / nullif(d.minutes * d.opp_possessions, 0), 1) end as steal_pct,
    case when d.box_score_complete then
        round(100 * (d.blocks * d.team_game_minutes)
            / nullif(d.minutes * (d.opp_field_goals_attempted
            - d.opp_three_pointers_attempted), 0), 1) end as block_pct,

    -- Per-36 production
    round(36 * d.points / nullif(d.minutes, 0), 1)        as points_per_36,
    case when d.box_score_complete then
        round(36 * d.total_rebounds / nullif(d.minutes, 0), 1) end as rebounds_per_36,
    case when d.box_score_complete then
        round(36 * d.assists / nullif(d.minutes, 0), 1) end       as assists_per_36,

    -- Per-100 possessions the player was on the floor for
    round(100 * d.points
        / nullif(d.minutes_share * d.team_possessions, 0), 1) as points_per_100,
    round(100 * d.total_rebounds
        / nullif(d.minutes_share * d.team_possessions, 0), 1) as rebounds_per_100,
    round(100 * d.assists
        / nullif(d.minutes_share * d.team_possessions, 0), 1) as assists_per_100,

    -- Hollinger game score, averaged per game
    case when d.box_score_complete then
        round((d.points + 0.4 * d.field_goals_made - 0.7 * d.field_goals_attempted
            - 0.4 * (d.free_throws_attempted - d.free_throws_made)
            + 0.7 * d.offensive_rebounds + 0.3 * d.defensive_rebounds + d.steals
            + 0.7 * d.assists + 0.7 * d.blocks - 0.4 * d.personal_fouls - d.turnovers)
            / nullif(d.games_played, 0), 1) end        as game_score,
    round(d.plus_minus_per_game, 1)                    as plus_minus,
    d.box_score_complete,

    -- On/off efficiency and PIE cannot be recovered from box score totals
    -- (they need who was on the floor), so these are published-only and
    -- stay null before 1996-97.
    a.offensive_rating        as offensive_rating,
    a.defensive_rating        as defensive_rating,
    a.net_rating              as net_rating,
    a.player_impact_estimate  as player_impact_estimate,
    a.offensive_rating is not null as has_official_advanced
from derived d
left join {{ ref('stg_player_advanced') }} a
       on a.season = d.season
      and a.player_id = d.player_id
