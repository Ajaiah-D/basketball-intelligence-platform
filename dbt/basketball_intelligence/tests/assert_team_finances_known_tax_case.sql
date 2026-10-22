-- The 2009-10 Boston Celtics are a real, well-documented luxury-tax-paying
-- team (team_payroll ~$83.55M against a $69.92M luxury tax line that season -
-- see docs/superpowers/plans/2026-09-23-team-payroll-cap-history.md's Task 2
-- fixture, which verifies the payroll figure by hand-summing the real page,
-- and Task 1's seed for the tax line).
-- If this row isn't flagged over_tax, either the payroll ingestion or the
-- mart's comparison logic is wrong.
--
-- The expected row is left-joined to the mart, so a row that has gone
-- missing fails here too: filtering the mart for it would find nothing and
-- pass. The row is in CI's fixtures (data/fixtures/team_payroll/2009-10).
with expected as (
    select * from (values
        ('2009-10', 'BOS', true)
    ) t(season, team_abbreviation, over_tax)
)

select e.season, e.team_abbreviation, f.team_payroll, f.luxury_tax,
       e.over_tax as expected_over_tax, f.over_tax,
       case when f.season is null then 'missing from the mart' else 'wrong' end as problem
from expected e
left join {{ ref('mart_team_finances') }} f using (season, team_abbreviation)
where f.over_tax is distinct from e.over_tax
