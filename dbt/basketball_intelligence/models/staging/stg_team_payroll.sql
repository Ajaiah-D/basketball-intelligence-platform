-- One row per team per season: total payroll, typed and lightly cleaned.
--
-- Deliberately unfiltered. An earlier draft had `where team_payroll > 0`,
-- which silently drops the 9 team-seasons whose source page has no salary
-- table at all (6 in 1986-87, 3 in 1989-90) - the exact bug the ingestion
-- layer was just fixed to stop committing. A team-season that exists in
-- raw.team_payroll must survive to the mart so payroll_likely_incomplete can
-- mark it; filtering here just moves the invisibility one layer down.

select
    cast(season as varchar)            as season,
    cast(team_abbreviation as varchar) as team_abbreviation,
    cast(team_payroll as bigint)       as team_payroll,
    cast(player_count as integer)      as player_count
from {{ source('raw', 'team_payroll') }}
