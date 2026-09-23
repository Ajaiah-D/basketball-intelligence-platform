-- One row per team per season: payroll against that season's league-wide
-- cap/tax/apron thresholds. luxury_tax/first_apron/second_apron are null
-- for seasons before those rules existed (see salary_cap_history's own
-- description) - the corresponding over_* flag is null for those rows too,
-- not false, since "over a threshold that didn't exist" is not a meaningful
-- false.
--
-- payroll_likely_incomplete marks a team-season whose payroll figure should
-- not be read as that team's real payroll. Three independent conditions,
-- any of which is enough:
--
--   1. player_count < 9 - a directly observed fact: a total summed from
--      fewer than nine players is not a roster, whatever it adds up to. 9
--      is the real, verified floor of a genuine complete season in this
--      backfill (1998-99 HOU's lockout-shortened roster) - every other
--      non-gap season/team sits at 10 or above (1995-96 PHL). This was
--      originally set to "< 8" on the reasoning that 8 sat one row below
--      that floor; that reasoning was wrong; it was exactly at the floor.
--      The task 4 review caught 4 real 1986-87-and-1989-90-unrelated
--      team-seasons published as trustworthy at exactly player_count 8
--      (1984-85 WAS/DEN/LAC/UTH) - it is this condition's tightening from
--      8 to 9, not condition 3, that catches them.
--   2. payroll < 0.5 * that season's cap - a backstop for a season that has
--      a full-looking row count but implausible money. This arm is a proxy,
--      not a certainty: it also flags 1988-89 Miami (13 real players, 47%
--      of that year's cap) - a genuinely cheap first-year expansion roster,
--      not a source gap. Reads as "don't trust this number," which is still
--      the right call for an inaugural-season roster, but it's a different
--      kind of "incomplete" than the source-gap cases below.
--   3. season = '1984-85' - a third real source gap, distinct from the two
--      below and caught only after this mart's first review. Every one of
--      its 23 teams sits at player_count 6-12; the very next season,
--      1985-86, runs 12-15. Unlike 1986-87/1989-90, no row-count cutoff can
--      isolate it without a collision: tightening the numeric threshold far
--      enough to catch 1984-85's 9-count teams (ATL, DAL, NJN, NYK, SAN)
--      would also wrongly flag 1998-99 HOU's legitimate 9-count season -
--      the two are numerically identical and only distinguishable by which
--      season they're in. This is the one deliberate season-level
--      exception in this mart, made because the general rule provably
--      cannot express it; conditions 1 and 2 remain general and are what
--      catch every other gap, including within 1984-85 itself for its
--      6-8-count teams.
--
-- payroll_incomplete_reason says WHICH of those fired, because they do not
-- mean the same thing to a reader and the dashboard has to be able to tell
-- them apart. It is null exactly when payroll_likely_incomplete is false:
--
--   'no_source_data'     - the team's page has no salary table at all
--                          (player_count 0, payroll null). Nothing to show.
--   'sparse_source_data' - a salary table exists but is missing most of the
--                          roster (player_count < 9), or the row is in
--                          1984-85, whose whole season is a source gap.
--                          Both are "Basketball-Reference's records for
--                          that season are incomplete."
--   'below_half_cap'     - row count looks complete but the money is under
--                          half the cap. USUALLY also a source gap, but not
--                          provably so: the only row in the current 1200
--                          that lands here alone is 1988-89 Miami, which is
--                          a real, complete, genuinely cheap inaugural
--                          expansion roster. Anything consuming this column
--                          must NOT tell a reader the source is missing
--                          data for a 'below_half_cap' season - say the
--                          number is unusually low, not that it is absent.
--
-- Condition 1 (after the fix above) is what matters for 1986-87 and
-- 1989-90: Basketball-Reference's historical salary data has genuine holes
-- there (1986-87 Denver's page has exactly one salaried player for the
-- whole team; every 1989-90 team has at most six rows). In 1989-90, eleven
-- teams clear 0.5x cap (52%-92%) on only 3-6 player rows, so the ratio
-- alone would pass them through as real - only player_count catches them.
-- A null payroll (player_count 0) is incomplete by definition.
--
-- Conditions 1 and 2 are general rules, not a hardcoded "skip this season",
-- so a future re-scrape that introduces a new gap is caught without another
-- manual audit - condition 3 is the one place that audit still matters.

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
    round(p.team_payroll / (1.0 * c.salary_cap), 3)  as payroll_pct_of_cap,
    coalesce(p.player_count < 9
             or p.team_payroll < (0.5 * c.salary_cap)
             or p.season = '1984-85', true)
                                                     as payroll_likely_incomplete,
    -- Ordered most-certain-first, so the reason names the strongest thing
    -- known about the row: a 1984-85 team with no salary table at all is
    -- 'no_source_data', not 'sparse_source_data'. The null-payroll arm is
    -- first for the same reason the flag above needs its coalesce - every
    -- comparison against a null payroll is null, not true.
    case
        when p.team_payroll is null or p.player_count = 0 then 'no_source_data'
        when p.player_count < 9 or p.season = '1984-85'   then 'sparse_source_data'
        when p.team_payroll < (0.5 * c.salary_cap)        then 'below_half_cap'
    end                                              as payroll_incomplete_reason,
    p.team_payroll > c.salary_cap                    as over_cap,
    case when c.luxury_tax is not null
         then p.team_payroll > c.luxury_tax end       as over_tax,
    case when c.first_apron is not null
         then p.team_payroll > c.first_apron end      as over_first_apron,
    case when c.second_apron is not null
         then p.team_payroll > c.second_apron end     as over_second_apron
from payroll p
join cap_history c on p.season = c.season
