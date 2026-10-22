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
--
-- The expected row is left-joined to the mart, so the row going missing
-- fails too. It is in CI's fixtures (data/fixtures/team_payroll/1998-99).
with expected as (
    select * from (values
        ('1998-99', 'HOU', 9, false)
    ) t(season, team_abbreviation, player_count, payroll_likely_incomplete)
)

select e.season, e.team_abbreviation, f.team_payroll, f.player_count,
       f.salary_cap, f.payroll_likely_incomplete,
       case when f.season is null then 'missing from the mart' else 'wrong' end as problem
from expected e
left join {{ ref('mart_team_finances') }} f using (season, team_abbreviation)
where f.payroll_likely_incomplete is distinct from e.payroll_likely_incomplete
   or f.player_count is distinct from e.player_count
