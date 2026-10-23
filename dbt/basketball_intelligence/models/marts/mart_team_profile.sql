-- One row per team per season: every team stat the diagnosis views compare,
-- with the team's rank and percentile in that season's league beside it.
-- The values come from mart_team_season (so they are the same numbers the
-- rest of the site shows) plus the three-point shooting and shot-mix
-- columns, which that mart does not carry.
--
-- Rank 1 is the best team in the season and percentile 100 is the best
-- (see the season_rank macro). Which end is best differs by stat: lower is
-- better for defensive rating, turnover rate, and the opponent's eFG%,
-- three-point % and free throw rate. Pace and the three-point rates are
-- style, not quality - a fast team is not a better team - so for them rank
-- 1 means the most, not the best.
--
-- Stats the source does not have stay null, and a null stat gets a null
-- rank and percentile. Early seasons are mostly null (1979-80 has no field
-- goal attempts, 1984-85 no three-point attempts).

with three_point as (
    select
        t.season,
        t.team_id,
        -- Same sum()-skips-nulls guard as mart_team_season: a single game
        -- missing one of a ratio's inputs would put that game's makes in
        -- the numerator and none of its attempts in the denominator, so
        -- the ratio is withheld for the season. Each ratio checks only its
        -- own inputs, and the opponent side is checked separately.
        count(*) filter (
            where t.three_pointers_made is null
               or t.three_pointers_attempted is null
        )                                   as incomplete_three_pt,
        count(*) filter (
            where t.three_pointers_attempted is null
               or t.field_goals_attempted is null
        )                                   as incomplete_three_rate,
        count(*) filter (
            where o.three_pointers_made is null
               or o.three_pointers_attempted is null
        )                                   as incomplete_opp_three_pt,
        count(*) filter (
            where o.three_pointers_attempted is null
               or o.field_goals_attempted is null
        )                                   as incomplete_opp_three_rate,
        sum(t.three_pointers_made)          as three_pointers_made,
        sum(t.three_pointers_attempted)     as three_pointers_attempted,
        sum(t.field_goals_attempted)        as field_goals_attempted,
        sum(o.three_pointers_made)          as opp_three_pointers_made,
        sum(o.three_pointers_attempted)     as opp_three_pointers_attempted,
        sum(o.field_goals_attempted)        as opp_field_goals_attempted
    from {{ ref('stg_team_game_logs') }} t
    join {{ ref('stg_team_game_logs') }} o
      on t.game_id = o.game_id
     and t.team_id <> o.team_id
    group by t.season, t.team_id
),

team_values as (
    select
        s.season,
        s.team_id,
        s.team_abbreviation,
        s.offensive_rating,
        s.defensive_rating,
        s.net_rating,
        s.pace,
        s.effective_fg_pct,
        s.turnover_pct,
        s.offensive_rebound_pct,
        s.free_throw_rate,
        s.assist_pct,
        s.opp_effective_fg_pct,
        s.opp_turnover_pct,
        s.defensive_rebound_pct,
        s.opp_free_throw_rate,
        case when p.incomplete_three_pt > 0 then null else
            round(100 * p.three_pointers_made
                / nullif(p.three_pointers_attempted, 0), 1) end       as three_pt_pct,
        case when p.incomplete_three_rate > 0 then null else
            round(100 * p.three_pointers_attempted
                / nullif(p.field_goals_attempted, 0), 1) end          as three_pt_rate,
        case when p.incomplete_opp_three_pt > 0 then null else
            round(100 * p.opp_three_pointers_made
                / nullif(p.opp_three_pointers_attempted, 0), 1) end   as opp_three_pt_pct,
        case when p.incomplete_opp_three_rate > 0 then null else
            round(100 * p.opp_three_pointers_attempted
                / nullif(p.opp_field_goals_attempted, 0), 1) end      as opp_three_pt_rate
    from {{ ref('mart_team_season') }} s
    left join three_point p
           on p.season = s.season
          and p.team_id = s.team_id
)

select
    *,
    {{ season_rank('offensive_rating', 'high') }},
    {{ season_rank('defensive_rating', 'low') }},
    {{ season_rank('net_rating', 'high') }},
    {{ season_rank('pace', 'high') }},
    {{ season_rank('effective_fg_pct', 'high') }},
    {{ season_rank('turnover_pct', 'low') }},
    {{ season_rank('offensive_rebound_pct', 'high') }},
    {{ season_rank('free_throw_rate', 'high') }},
    {{ season_rank('assist_pct', 'high') }},
    {{ season_rank('opp_effective_fg_pct', 'low') }},
    {{ season_rank('opp_turnover_pct', 'high') }},
    {{ season_rank('defensive_rebound_pct', 'high') }},
    {{ season_rank('opp_free_throw_rate', 'low') }},
    {{ season_rank('three_pt_pct', 'high') }},
    {{ season_rank('three_pt_rate', 'high') }},
    {{ season_rank('opp_three_pt_pct', 'low') }},
    {{ season_rank('opp_three_pt_rate', 'high') }}
from team_values
