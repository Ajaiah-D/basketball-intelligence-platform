-- Every (season, code) in the payroll must be covered by a team_codes era.
-- The Finances page files each payroll row under a franchise and an era
-- name through that seed (core/teams.py), and an uncovered code there
-- raises instead of guessing. assert_standings_conference_is_assigned
-- only sees the codes in the game logs; the payroll comes from a second
-- source (Basketball-Reference, mapped back to nba_api codes), so its
-- codes get their own check here and an uncovered one fails the build
-- before the page does.
--
-- Same code-and-season-range join as mart_team_standings.

select p.season, p.team_abbreviation
from (
    select distinct season, team_abbreviation from {{ ref('stg_team_payroll') }}
) p
left join {{ ref('team_codes') }} c
  on c.team_code = p.team_abbreviation
 and (c.first_season is null or p.season >= c.first_season)
 and (c.last_season is null or p.season <= c.last_season)
where c.team_code is null
