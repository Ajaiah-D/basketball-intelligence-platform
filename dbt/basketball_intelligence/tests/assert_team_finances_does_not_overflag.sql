-- CI note: this row (1998-99 HOU) is NOT in CI's reduced fixture set (see
-- assert_team_finances_flags_incomplete_payroll.sql for the same caveat) -
-- this test passes vacuously in CI and only earns its keep against a full
-- local warehouse.
--
-- The mirror image of assert_team_finances_flags_incomplete_payroll: a real,
-- legitimate team-season that must NOT come out flagged, so a future edit
-- that further tightens player_count (or widens the 1984-85 exception)
-- fails here instead of silently degrading trust in genuinely complete data.
--
-- 1998-99 HOU - the lockout-shortened season's real floor: 9 salary rows,
-- the same count 1984-85's own thin teams sit at, but this one is real and
-- complete. This is exactly the case that made a flat "player_count < N"
-- rule alone insufficient - raising N to catch 1984-85's 9-count teams
-- would also catch this one, so 1984-85 gets an explicit season condition
-- instead of a lower N. If this row starts failing, the threshold moved.
select season, team_abbreviation, team_payroll, player_count, salary_cap,
       payroll_likely_incomplete
from {{ ref('mart_team_finances') }}
where season = '1998-99'
  and team_abbreviation = 'HOU'
  and (payroll_likely_incomplete is distinct from false)
