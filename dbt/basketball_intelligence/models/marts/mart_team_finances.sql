-- One row per team per season: payroll against that season's league-wide
-- cap/tax/apron thresholds. luxury_tax/first_apron/second_apron are null
-- for seasons before those rules existed (see salary_cap_history's own
-- description) - the corresponding over_* flag is null for those rows too,
-- not false, since "over a threshold that didn't exist" is not a meaningful
-- false.
--
-- payroll_likely_incomplete marks a team-season whose payroll figure should
-- not be read as that team's real payroll. Two independent conditions,
-- either of which is enough:
--
--   1. player_count < 8 - a directly observed fact: a total summed from
--      fewer than eight players is not a roster, whatever it adds up to.
--      Across this backfill's non-gap seasons, real row counts run 9-39
--      (1998-99 HOU's lockout-shortened roster is the thinnest real one, at
--      9; 89% of non-gap rows fall in 11-21) - so 8 sits exactly one row
--      below the lowest genuine case found. Don't nudge this threshold up
--      without re-checking that margin.
--   2. payroll < 0.5 * that season's cap - a backstop for a season that has
--      a full-looking row count but implausible money. This arm is a proxy,
--      not a certainty: it also flags 1988-89 Miami (13 real players, 47%
--      of that year's cap) - a genuinely cheap first-year expansion roster,
--      not a source gap. Reads as "don't trust this number," which is still
--      the right call for an inaugural-season roster, but it's a different
--      kind of "incomplete" than the source-gap cases below.
--
-- Condition 1 is the one that matters for the two real source gaps this
-- backfill found: Basketball-Reference's historical salary data has genuine
-- holes in 1986-87 (Denver's page has exactly one salaried player for the
-- whole team) and 1989-90 (every team has at most six rows). In 1989-90,
-- eleven teams clear 0.5x cap (52%-92%) on only 3-6 player rows, so the
-- ratio alone would pass them through as real - only player_count catches
-- them. A null payroll (player_count 0) is incomplete by definition.
--
-- Both are general rules, not a hardcoded "skip 1986-87/1989-90", so a
-- future re-scrape that introduces a new gap is caught without another
-- manual season-by-season audit.

with payroll as (
    select * from {{ ref('stg_team_payroll') }}
),

cap_history as (
    select * from {{ ref('salary_cap_history') }}
)

select
    p.season,
    p.team_abbreviation,
    p.team_payroll,
    p.player_count,
    c.salary_cap,
    c.luxury_tax,
    c.first_apron,
    c.second_apron,
    round(p.team_payroll / c.salary_cap, 3)          as payroll_pct_of_cap,
    coalesce(p.player_count < 8
             or p.team_payroll < (0.5 * c.salary_cap), true)
                                                     as payroll_likely_incomplete,
    p.team_payroll > c.salary_cap                    as over_cap,
    case when c.luxury_tax is not null
         then p.team_payroll > c.luxury_tax end       as over_tax,
    case when c.first_apron is not null
         then p.team_payroll > c.first_apron end      as over_first_apron,
    case when c.second_apron is not null
         then p.team_payroll > c.second_apron end     as over_second_apron
from payroll p
join cap_history c on p.season = c.season
