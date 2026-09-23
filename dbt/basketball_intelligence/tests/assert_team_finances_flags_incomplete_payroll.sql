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
select season, team_abbreviation, team_payroll, player_count, salary_cap,
       payroll_likely_incomplete
from {{ ref('mart_team_finances') }}
where (season, team_abbreviation) in (
        ('1986-87', 'DEN'), ('1989-90', 'BOS'), ('1986-87', 'GOS'), ('1984-85', 'NYK'))
  and (payroll_likely_incomplete is distinct from true)
