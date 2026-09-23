-- The 2009-10 Boston Celtics are a real, well-documented luxury-tax-paying
-- team (team_payroll ~$83.55M against a $69.92M luxury tax line that season -
-- see docs/superpowers/plans/2026-09-23-team-payroll-cap-history.md's Task 2
-- fixture, which verifies the payroll figure by hand-summing the real page,
-- and Task 1's seed for the tax line).
-- If this row isn't flagged over_tax, either the payroll ingestion or the
-- mart's comparison logic is wrong.
select season, team_abbreviation, team_payroll, luxury_tax, over_tax
from {{ ref('mart_team_finances') }}
where season = '2009-10'
  and team_abbreviation = 'BOS'
  and (over_tax is distinct from true)
