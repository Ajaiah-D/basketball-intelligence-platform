-- mart_team_profile's ranks and percentiles must be real grades: a rank
-- inside 1..teams that season, a percentile inside 0..100, and the
-- direction right. The direction is the easy thing to get backwards (the
-- team with the most turnovers graded best), and nothing else would
-- notice, because every number would still be in range. Any row here is
-- a failure.

with profile as (
    select *, count(*) over (partition by season) as teams
    from {{ ref('mart_team_profile') }}
),

graded as (
    select season, team_abbreviation, teams, 'offensive_rating' as stat,
           offensive_rating as value, offensive_rating_rank as rnk,
           offensive_rating_pctile as pctile from profile
    union all
    select season, team_abbreviation, teams, 'defensive_rating',
           defensive_rating, defensive_rating_rank, defensive_rating_pctile from profile
    union all
    select season, team_abbreviation, teams, 'net_rating',
           net_rating, net_rating_rank, net_rating_pctile from profile
    union all
    select season, team_abbreviation, teams, 'pace',
           pace, pace_rank, pace_pctile from profile
    union all
    select season, team_abbreviation, teams, 'effective_fg_pct',
           effective_fg_pct, effective_fg_pct_rank, effective_fg_pct_pctile from profile
    union all
    select season, team_abbreviation, teams, 'turnover_pct',
           turnover_pct, turnover_pct_rank, turnover_pct_pctile from profile
    union all
    select season, team_abbreviation, teams, 'offensive_rebound_pct',
           offensive_rebound_pct, offensive_rebound_pct_rank,
           offensive_rebound_pct_pctile from profile
    union all
    select season, team_abbreviation, teams, 'free_throw_rate',
           free_throw_rate, free_throw_rate_rank, free_throw_rate_pctile from profile
    union all
    select season, team_abbreviation, teams, 'assist_pct',
           assist_pct, assist_pct_rank, assist_pct_pctile from profile
    union all
    select season, team_abbreviation, teams, 'opp_effective_fg_pct',
           opp_effective_fg_pct, opp_effective_fg_pct_rank,
           opp_effective_fg_pct_pctile from profile
    union all
    select season, team_abbreviation, teams, 'opp_turnover_pct',
           opp_turnover_pct, opp_turnover_pct_rank, opp_turnover_pct_pctile from profile
    union all
    select season, team_abbreviation, teams, 'defensive_rebound_pct',
           defensive_rebound_pct, defensive_rebound_pct_rank,
           defensive_rebound_pct_pctile from profile
    union all
    select season, team_abbreviation, teams, 'opp_free_throw_rate',
           opp_free_throw_rate, opp_free_throw_rate_rank,
           opp_free_throw_rate_pctile from profile
    union all
    select season, team_abbreviation, teams, 'three_pt_pct',
           three_pt_pct, three_pt_pct_rank, three_pt_pct_pctile from profile
    union all
    select season, team_abbreviation, teams, 'three_pt_rate',
           three_pt_rate, three_pt_rate_rank, three_pt_rate_pctile from profile
    union all
    select season, team_abbreviation, teams, 'opp_three_pt_pct',
           opp_three_pt_pct, opp_three_pt_pct_rank, opp_three_pt_pct_pctile from profile
    union all
    select season, team_abbreviation, teams, 'opp_three_pt_rate',
           opp_three_pt_rate, opp_three_pt_rate_rank, opp_three_pt_rate_pctile from profile
),

-- Which end of each stat is rank 1: 'high' is the largest value. Pace and
-- the three-point rates are style stats, where rank 1 means the most.
direction as (
    select * from (values
        ('offensive_rating', 'high'), ('defensive_rating', 'low'),
        ('net_rating', 'high'), ('pace', 'high'),
        ('effective_fg_pct', 'high'), ('turnover_pct', 'low'),
        ('offensive_rebound_pct', 'high'), ('free_throw_rate', 'high'),
        ('assist_pct', 'high'), ('opp_effective_fg_pct', 'low'),
        ('opp_turnover_pct', 'high'), ('defensive_rebound_pct', 'high'),
        ('opp_free_throw_rate', 'low'), ('three_pt_pct', 'high'),
        ('three_pt_rate', 'high'), ('opp_three_pt_pct', 'low'),
        ('opp_three_pt_rate', 'high')
    ) as d (stat, best)
),

best_value as (
    select g.season, g.stat,
           case when d.best = 'high' then max(g.value) else min(g.value) end as best
    from graded g
    join direction d on d.stat = g.stat
    group by g.season, g.stat, d.best
)

-- A rank outside 1..teams, or a percentile outside 0..100
select 'out of range' as problem, season, team_abbreviation, stat, value
from graded
where (rnk is not null and (rnk < 1 or rnk > teams))
   or (pctile is not null and (pctile < 0 or pctile > 100))

union all

-- A null value must have a null rank and percentile, and a value must
-- have both
select 'null mismatch', season, team_abbreviation, stat, value
from graded
where (value is null) <> (rnk is null)
   or (rnk is null) <> (pctile is null)

union all

-- Direction: whoever holds the best value in a season is rank 1 and
-- percentile 100, and nobody else is rank 1. With the direction backwards
-- the worst turnover team would hold rank 1.
select 'direction', g.season, g.team_abbreviation, g.stat, g.value
from graded g
join best_value b on b.season = g.season and b.stat = g.stat
where (g.value = b.best and (g.rnk <> 1 or g.pctile <> 100))
   or (g.value is distinct from b.best and g.rnk = 1)
