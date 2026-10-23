-- The qualification rule's early-season branch. Every finished season is
-- at the 25-game cap, so the real marts never exercise the scaling. This
-- applies the same qualification_games macro mart_player_percentiles uses
-- to made-up "most games played" values, against the answers of the
-- dashboard's Python rule (qualification_threshold: max(1, min(25,
-- int(0.6 x max games)))). tests/test_player_percentiles.py checks that
-- this table equals the Python function, so the two stay in step. Any row
-- here is a failure.

with cases as (
    select * from (values
        (1, 1), (3, 1), (5, 3), (9, 5), (10, 6),
        (30, 18), (41, 24), (42, 25), (82, 25)
    ) as c (max_gp, expected)
)

select max_gp, expected, {{ qualification_games('max_gp') }} as actual
from cases
where {{ qualification_games('max_gp') }} <> expected
