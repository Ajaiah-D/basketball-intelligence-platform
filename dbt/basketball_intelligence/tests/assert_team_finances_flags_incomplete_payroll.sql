-- Four real, verified source gaps that must all come out flagged. Each one
-- exercises a different arm of the rule, so a regression in any arm fails
-- here rather than on a public chart:
--
--   1986-87 DEN - one salaried player on record (Mike Evans, $75,000).
--                 Caught by both the ratio and the row count.
--   1989-90 BOS - $5,950,000 from THREE player rows, which is 61% of that
--                 season's cap. The ratio check passes it; only
--                 player_count catches it. This is the case the original
--                 0.5x-cap-only rule missed entirely.
--   1986-87 GOS - no salary table at all: null payroll, player_count 0.
--                 Must still be a row here, and must be flagged.
--   1984-85 NYK - $3,952,000 from NINE player rows: above 0.5x that
--                 season's $3.6M cap (fails the ratio arm) and at exactly
--                 9 rows (fails the player_count<9 arm too - 9 is the
--                 real, verified floor of a genuine season elsewhere in
--                 this data). Only the explicit season='1984-85' condition
--                 catches it. This is the case a second review round found
--                 the row-count-only rule couldn't express without also
--                 mis-flagging a real, legitimate 9-row season elsewhere
--                 (1998-99 HOU).
--
-- The reason is pinned too, since each case says which arm fired: GOS has
-- nothing to show, the other three are thin source records.
--
-- Expected rows are left-joined to the mart, so a row that has gone missing
-- fails rather than passing as an empty match - GOS especially, whose
-- whole point is that a team with no salary table still gets a row. All
-- four are in CI's fixtures (data/fixtures/team_payroll/).
with expected as (
    select * from (values
        ('1986-87', 'DEN', true, 'sparse_source_data'),
        ('1989-90', 'BOS', true, 'sparse_source_data'),
        ('1986-87', 'GOS', true, 'no_source_data'),
        ('1984-85', 'NYK', true, 'sparse_source_data')
    ) t(season, team_abbreviation, payroll_likely_incomplete, payroll_incomplete_reason)
)

select e.season, e.team_abbreviation, f.team_payroll, f.player_count,
       f.salary_cap, f.payroll_likely_incomplete, f.payroll_incomplete_reason,
       case when f.season is null then 'missing from the mart' else 'wrong' end as problem
from expected e
left join {{ ref('mart_team_finances') }} f using (season, team_abbreviation)
where f.payroll_likely_incomplete is distinct from e.payroll_likely_incomplete
   or f.payroll_incomplete_reason is distinct from e.payroll_incomplete_reason
