-- 1988-89 MIA is the one row in the whole 1200 that is flagged
-- payroll_likely_incomplete for the ratio arm ALONE: an inaugural expansion
-- roster of 13 real, complete salary rows totalling 47% of that season's
-- cap. Basketball-Reference is missing nothing here; the team really was
-- that cheap.
--
-- Before payroll_incomplete_reason existed, the Finances page told users
-- that "Basketball-Reference's own salary records for that season are
-- missing most of the roster" about this row - a factually wrong published
-- claim about a real NBA team's real history. The fix is that this row must
-- come out 'below_half_cap' and never 'sparse_source_data'/'no_source_data',
-- so the page can say "unusually low" instead of "missing".
--
-- The expected row is left-joined to the mart, so the row going missing
-- fails too. It is in CI's fixtures (data/fixtures/team_payroll/1988-89).
with expected as (
    select * from (values
        ('1988-89', 'MIA', 13, 'below_half_cap')
    ) t(season, team_abbreviation, player_count, payroll_incomplete_reason)
)

select e.season, e.team_abbreviation, f.player_count, f.payroll_pct_of_cap,
       f.payroll_incomplete_reason,
       case when f.season is null then 'missing from the mart' else 'wrong' end as problem
from expected e
left join {{ ref('mart_team_finances') }} f using (season, team_abbreviation)
where f.payroll_incomplete_reason is distinct from e.payroll_incomplete_reason
   or f.player_count is distinct from e.player_count
