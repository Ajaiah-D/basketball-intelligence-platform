-- payroll_incomplete_reason must be non-null for exactly the rows
-- payroll_likely_incomplete is true for, and null for every other row.
--
-- The two are written as separate expressions in mart_team_finances.sql (a
-- boolean OR and an ordered CASE), so nothing but this test stops them
-- drifting apart - and drift here is a silent correctness bug in both
-- directions: a flagged row with no reason makes the dashboard fall back to
-- whichever caption it treats as the default (today: "the source is missing
-- data", which is a false claim about a row like 1988-89 MIA), and an
-- unflagged row with a reason attaches a "don't trust this" explanation to
-- a number the chart is happily plotting as real.
select season, team_abbreviation, payroll_likely_incomplete,
       payroll_incomplete_reason
from {{ ref('mart_team_finances') }}
where payroll_likely_incomplete <> (payroll_incomplete_reason is not null)
