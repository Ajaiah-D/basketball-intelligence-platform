-- One row per team per season: efficiency ratings, pace and the four
-- factors.
--
-- The NBA only publishes official advanced stats from 1996-97, so ratings
-- are also estimated from box scores for every season back to 1979-80.
-- The published figures are used when they exist and the estimate fills in
-- before that; `ratings_source` says which one a row is carrying, and the
-- est_* columns stay exposed so the two can be compared directly.
--
-- Possessions use the Basketball Reference estimate, which tracks the
-- published numbers about a third closer than the plain
-- FGA + 0.44*FTA - OREB + TOV version (mean abs error 1.1 vs 1.6 points of
-- rating over the 892 team-seasons where both exist).

with paired as (
    select
        t.season,
        t.team_id,
        t.team_abbreviation,
        t.team_name,
        t.game_id,
        t.is_win,
        t.minutes_played,
        t.points,
        t.field_goals_made,
        t.field_goals_attempted,
        t.three_pointers_made,
        t.free_throws_made,
        t.free_throws_attempted,
        t.offensive_rebounds,
        t.defensive_rebounds,
        t.total_rebounds,
        t.assists,
        t.turnovers,
        o.points                  as opp_points,
        o.field_goals_made        as opp_field_goals_made,
        o.field_goals_attempted   as opp_field_goals_attempted,
        o.three_pointers_made     as opp_three_pointers_made,
        o.free_throws_attempted   as opp_free_throws_attempted,
        o.offensive_rebounds      as opp_offensive_rebounds,
        o.defensive_rebounds      as opp_defensive_rebounds,
        o.total_rebounds          as opp_total_rebounds,
        o.turnovers               as opp_turnovers
    from {{ ref('stg_team_game_logs') }} t
    join {{ ref('stg_team_game_logs') }} o
      on t.game_id = o.game_id
     and t.team_id <> o.team_id
),

totals as (
    select
        season,
        team_id,
        any_value(team_abbreviation) as team_abbreviation,
        any_value(team_name)         as team_name,
        count(*)                     as games_played,
        -- Box scores are only complete from 1985-86. Before that the source
        -- is a patchwork: 1979-80 has no field goal attempts, rebounds or
        -- assists at all, and 1984-85 is still missing 3PA, rebound splits
        -- and turnovers. sum() skips nulls silently, so without this guard a
        -- partial season yields a confident, badly wrong number (an early
        -- version of this model reported a 145 offensive rating and an eFG%
        -- of 800). Every column any derived metric touches is checked, and
        -- if a single game is missing one the season's derived metrics are
        -- withheld rather than estimated from a fraction of the games.
        count(*) filter (
            where field_goals_attempted is null
               or three_pointers_made is null
               or free_throws_attempted is null
               or offensive_rebounds is null
               or defensive_rebounds is null
               or total_rebounds is null
               or assists is null
               or turnovers is null
               or opp_field_goals_made is null
               or opp_field_goals_attempted is null
               or opp_three_pointers_made is null
               or opp_free_throws_attempted is null
               or opp_offensive_rebounds is null
               or opp_defensive_rebounds is null
               or opp_total_rebounds is null
               or opp_turnovers is null
        )                            as incomplete_games,
        sum(case when is_win then 1 else 0 end) as wins,
        sum(case when is_win then 0 else 1 end) as losses,
        sum(minutes_played)          as team_minutes,
        sum(points)                  as points,
        sum(opp_points)              as opp_points,
        sum(field_goals_made)        as field_goals_made,
        sum(field_goals_attempted)   as field_goals_attempted,
        sum(three_pointers_made)     as three_pointers_made,
        sum(free_throws_made)        as free_throws_made,
        sum(free_throws_attempted)   as free_throws_attempted,
        sum(offensive_rebounds)      as offensive_rebounds,
        sum(defensive_rebounds)      as defensive_rebounds,
        sum(total_rebounds)          as total_rebounds,
        sum(assists)                 as assists,
        sum(turnovers)               as turnovers,
        sum(opp_field_goals_made)      as opp_field_goals_made,
        sum(opp_field_goals_attempted) as opp_field_goals_attempted,
        sum(opp_three_pointers_made)   as opp_three_pointers_made,
        sum(opp_free_throws_attempted) as opp_free_throws_attempted,
        sum(opp_offensive_rebounds)    as opp_offensive_rebounds,
        sum(opp_defensive_rebounds)    as opp_defensive_rebounds,
        sum(opp_total_rebounds)        as opp_total_rebounds,
        sum(opp_turnovers)             as opp_turnovers
    from paired
    group by season, team_id
),

with_possessions as (
    select
        *,
        -- Averaged with the opponent's estimate so both teams in a game
        -- share a possession count, which is what makes pace symmetric.
        case when incomplete_games > 0 then null else 0.5 * (
            (field_goals_attempted + 0.4 * free_throws_attempted
                - 1.07 * (offensive_rebounds
                    / nullif(offensive_rebounds + opp_defensive_rebounds, 0))
                * (field_goals_attempted - field_goals_made) + turnovers)
          + (opp_field_goals_attempted + 0.4 * opp_free_throws_attempted
                - 1.07 * (opp_offensive_rebounds
                    / nullif(opp_offensive_rebounds + defensive_rebounds, 0))
                * (opp_field_goals_attempted - opp_field_goals_made) + opp_turnovers)
        ) end as possessions
    from totals
)

select
    t.season,
    t.team_id,
    t.team_abbreviation,
    t.team_name,
    t.games_played,
    t.wins,
    t.losses,
    round(t.wins / nullif(t.games_played, 0), 3)              as win_pct,
    round(t.points / nullif(t.games_played, 0), 1)            as points_per_game,
    round(t.opp_points / nullif(t.games_played, 0), 1)        as opp_points_per_game,

    -- Efficiency: points per 100 possessions. Published figure when the
    -- NBA has one, box-score estimate otherwise.
    coalesce(a.offensive_rating,
        round(100 * t.points / nullif(t.possessions, 0), 1))      as offensive_rating,
    coalesce(a.defensive_rating,
        round(100 * t.opp_points / nullif(t.possessions, 0), 1))  as defensive_rating,
    coalesce(a.net_rating,
        round(100 * (t.points - t.opp_points)
            / nullif(t.possessions, 0), 1))                       as net_rating,
    coalesce(a.pace,
        round(48 * t.possessions / nullif(t.team_minutes / 5.0, 0), 1)) as pace,
    case when a.offensive_rating is not null then 'NBA official'
         when t.possessions is not null then 'estimated from box score'
         else 'not available before 1985-86' end                  as ratings_source,

    -- The box-score estimate, kept alongside so the two can be compared
    round(100 * t.points / nullif(t.possessions, 0), 1)       as est_offensive_rating,
    round(100 * t.opp_points / nullif(t.possessions, 0), 1)   as est_defensive_rating,
    round(48 * t.possessions / nullif(t.team_minutes / 5.0, 0), 1) as est_pace,

    -- Four factors. Exact from box score totals wherever the box score is
    -- complete, so no published counterpart is needed.
    case when t.incomplete_games > 0 then null else
        round(100 * (t.field_goals_made + 0.5 * t.three_pointers_made)
            / nullif(t.field_goals_attempted, 0), 1) end      as effective_fg_pct,
    case when t.incomplete_games > 0 then null else
        round(100 * t.turnovers / nullif(t.field_goals_attempted
            + 0.44 * t.free_throws_attempted + t.turnovers, 0), 1) end as turnover_pct,
    case when t.incomplete_games > 0 then null else
        round(100 * t.offensive_rebounds
            / nullif(t.offensive_rebounds + t.opp_defensive_rebounds, 0), 1) end
                                                              as offensive_rebound_pct,
    case when t.incomplete_games > 0 then null else
        round(100 * t.free_throws_made / nullif(t.field_goals_attempted, 0), 1) end
                                                              as free_throw_rate,

    -- Four factors, defense (what the opponent managed)
    case when t.incomplete_games > 0 then null else
        round(100 * (t.opp_field_goals_made + 0.5 * t.opp_three_pointers_made)
            / nullif(t.opp_field_goals_attempted, 0), 1) end  as opp_effective_fg_pct,
    case when t.incomplete_games > 0 then null else
        round(100 * t.opp_turnovers / nullif(t.opp_field_goals_attempted
            + 0.44 * t.opp_free_throws_attempted + t.opp_turnovers, 0), 1) end
                                                              as opp_turnover_pct,
    case when t.incomplete_games > 0 then null else
        round(100 * t.defensive_rebounds
            / nullif(t.defensive_rebounds + t.opp_offensive_rebounds, 0), 1) end
                                                              as defensive_rebound_pct,

    case when t.incomplete_games > 0 then null else
        round(100 * t.points / nullif(2 * (t.field_goals_attempted
            + 0.44 * t.free_throws_attempted), 0), 1) end     as true_shooting_pct,
    case when t.incomplete_games > 0 then null else
        round(100 * t.assists / nullif(t.field_goals_made, 0), 1) end as assist_pct,
    t.incomplete_games = 0                                    as box_score_complete
from with_possessions t
left join {{ ref('stg_team_advanced') }} a
       on a.season = t.season
      and a.team_id = t.team_id
