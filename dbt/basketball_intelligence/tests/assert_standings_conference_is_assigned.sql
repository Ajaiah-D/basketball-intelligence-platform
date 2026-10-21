-- Every team abbreviation that appears in the data must get a conference
-- from the team_codes seed in mart_team_standings.
--
-- This exists because the conference map used to end in `else 'West'`.
-- That default is silent: PHL (Philadelphia, 1979-80 through 1995-96) was
-- filed in the West for 17 seasons and nothing complained, because a
-- default always produces an answer. The mart now left-joins the seed on
-- code and season range with no default, so an uncovered abbreviation
-- produces a null - and this test turns that null into a failed build.
--
-- Two ways an abbreviation can go unassigned, both caught here:
--
-- 1. It reaches the mart but no seed era covers it, so conference is null
--    (or, if someone reintroduces a default, is not one of the two legal
--    values).
--
-- 2. It never reaches the mart at all. That is not a conference bug on
--    its own, but it means this test could not have seen it, so failing
--    is the honest outcome - a code present in the game logs and absent
--    from the standings is a real gap either way.

select
    team_abbreviation,
    'conference is not East or West' as problem
from {{ ref('mart_team_standings') }}
where conference is null or conference not in ('East', 'West')

union all

select
    l.team_abbreviation,
    'abbreviation in stg_team_game_logs never reaches mart_team_standings' as problem
from (select distinct team_abbreviation from {{ ref('stg_team_game_logs') }}) l
left join (
    select distinct team_abbreviation from {{ ref('mart_team_standings') }}
) s on s.team_abbreviation = l.team_abbreviation
where s.team_abbreviation is null
