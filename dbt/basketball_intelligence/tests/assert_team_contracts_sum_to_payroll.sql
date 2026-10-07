-- The contracts list and the payroll figure come from the same scrape of the
-- same salary rows, so for every team-season with player rows they must
-- agree to the dollar. A mismatch means the two raw files came from
-- different scrapes and the page would show a list that doesn't add up.
select f.season, f.team_abbreviation, f.team_payroll, c.total
from {{ ref('mart_team_finances') }} f
join (
    select season, team_abbreviation, sum(salary_usd) as total
    from {{ ref('mart_team_contracts') }}
    group by 1, 2
) c using (season, team_abbreviation)
where f.team_payroll <> c.total
