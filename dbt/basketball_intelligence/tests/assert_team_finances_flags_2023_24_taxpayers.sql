-- The eight teams that actually paid luxury tax for 2023-24 (Warriors,
-- Clippers, Suns, Bucks, Celtics, Nuggets, Heat, Lakers - $521.8M in total,
-- per the league's end-of-season figures as reported by Hoops Rumors, June
-- 2024) must all be over_tax in the mart. This is the one season where the
-- payroll approximation has been checked against the official outcome.
--
-- It is deliberately one-directional. The mart also puts four teams over the
-- line that did not pay (CHI, PHI, POR, NYK, each by under $2.5M): payroll
-- here is the end-of-season roster at full salaries, while the real bill
-- prorates mid-season trades, so a team that ducked under at the deadline
-- still reads as marginally over. dashboard/lib/payroll.py's METHOD_NOTE
-- says so on the page. A real taxpayer going missing would be a data bug;
-- a marginal extra is the documented approximation.
--
-- Expected rows are left-joined to the mart, so a taxpayer missing from it
-- fails as surely as one that isn't flagged. CI's fixtures carry exactly
-- these eight 2023-24 team-seasons (data/fixtures/team_payroll/2023-24).
with expected as (
    select * from (values
        ('2023-24', 'GSW', true),
        ('2023-24', 'LAC', true),
        ('2023-24', 'PHX', true),
        ('2023-24', 'MIL', true),
        ('2023-24', 'BOS', true),
        ('2023-24', 'DEN', true),
        ('2023-24', 'MIA', true),
        ('2023-24', 'LAL', true)
    ) t(season, team_abbreviation, over_tax)
)

select e.season, e.team_abbreviation, f.team_payroll, f.luxury_tax,
       e.over_tax as expected_over_tax, f.over_tax,
       case when f.season is null then 'missing from the mart' else 'wrong' end as problem
from expected e
left join {{ ref('mart_team_finances') }} f using (season, team_abbreviation)
where f.over_tax is distinct from e.over_tax
