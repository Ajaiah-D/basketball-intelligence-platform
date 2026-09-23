-- Three real, verified source gaps that must all come out flagged. Each one
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
select season, team_abbreviation, team_payroll, player_count, salary_cap,
       payroll_likely_incomplete
from {{ ref('mart_team_finances') }}
where (season, team_abbreviation) in (
        ('1986-87', 'DEN'), ('1989-90', 'BOS'), ('1986-87', 'GOS'))
  and (payroll_likely_incomplete is distinct from true)
