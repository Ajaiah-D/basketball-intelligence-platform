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
-- CI note: CI builds from a reduced fixture set covering only 1984-85 and
-- 2024-25, so this row does not exist there and this test passes vacuously
-- in CI - same caveat as assert_team_finances_flags_incomplete_payroll. It
-- earns its keep against a full local warehouse.
select season, team_abbreviation, player_count, payroll_pct_of_cap,
       payroll_incomplete_reason
from {{ ref('mart_team_finances') }}
where season = '1988-89'
  and team_abbreviation = 'MIA'
  and (payroll_incomplete_reason is distinct from 'below_half_cap')
