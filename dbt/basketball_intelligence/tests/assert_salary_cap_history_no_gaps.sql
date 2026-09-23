-- salary_cap_history must have no gaps, in two senses.
--
-- 1. No MISSING SEASON ROW. Every season from 1984-85 through the later of
--    the seed's own last season and stg_team_payroll's last season must
--    exist as a row here. Until this arm was added the test only checked
--    for null cells within existing rows, so a season silently dropped from
--    the seed entirely passed it - and mart_team_finances inner-joins this
--    seed, so one dropped row quietly deletes ~30 team-seasons from the
--    mart with the grain test still green (a unique grain over fewer rows
--    is still a unique grain). The lower bound is the literal 1984, not
--    min(season): deriving it from the data would let a dropped 1984-85 row
--    redefine the range it was supposed to fail against. The UPPER bound
--    is data-derived and so cannot catch a dropped last row - but the
--    seed deliberately runs one season ahead of stg_team_payroll (the
--    cap for next season is announced before anyone is paid under it),
--    and a row with no payroll rows behind it costs the mart nothing.
--    Verified by negative control: deleting 2000-01 fails this test, and
--    so does deleting 1984-85.
--
-- 2. No unexpected nulls within each rule's applicable era: luxury_tax from
--    2002-03 on, first/second apron from 2023-24 on. Nulls before those
--    seasons are correct (the rule didn't exist) and are excluded here, not
--    flagged.

-- Arm 1. Seasons are 'YYYY-YY', so the start year alone orders and counts them.
with bounds as (
    select
        least(1984, (select min(cast(substr(season, 1, 4) as integer))
                     from {{ ref('stg_team_payroll') }}))     as first_year,
        greatest(
            (select max(cast(substr(season, 1, 4) as integer))
             from {{ ref('salary_cap_history') }}),
            (select max(cast(substr(season, 1, 4) as integer))
             from {{ ref('stg_team_payroll') }}))             as last_year
),

expected as (
    select unnest(generate_series(first_year, last_year)) as start_year
    from bounds
),

present as (
    select cast(substr(season, 1, 4) as integer) as start_year
    from {{ ref('salary_cap_history') }}
)

select
    e.start_year || '-' || right('0' || ((e.start_year + 1) % 100)::varchar, 2)
                             as season,
    'missing_season_row'     as missing_column
from expected e
left join present p on p.start_year = e.start_year
where p.start_year is null

union all

-- Arm 2 has one documented exception: under the pre-2011 CBA, the luxury
-- tax only applied in a season if league-wide player spending exceeded
-- 61.1% of basketball-related income (BRI) that season. In 2004-05
-- spending came in at 60.4% of BRI - under the trigger - so no tax was collected and no
-- operative threshold figure exists for that season (unlike 2001-02, where
-- the tax mechanism itself hadn't been introduced yet). This is a real
-- historical fact, independently corroborated (e.g. Forbes' "Complete
-- History Of NBA Luxury Tax Payments, 2001-2022"), not a research gap.
select season, 'luxury_tax' as missing_column
from {{ ref('salary_cap_history') }}
where season >= '2002-03'
  and luxury_tax is null
  and season <> '2004-05'

union all

select season, 'first_apron' as missing_column
from {{ ref('salary_cap_history') }}
where season >= '2023-24' and first_apron is null

union all

select season, 'second_apron' as missing_column
from {{ ref('salary_cap_history') }}
where season >= '2023-24' and second_apron is null
