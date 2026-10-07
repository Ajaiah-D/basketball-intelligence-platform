-- One row per player per team-season. Two 10-day contracts with the same
-- team are two salary lines in the source; the mart sums them into one row,
-- so the contracts list never shows a player twice.
select season, team_abbreviation, bbref_player_id, count(*) as n
from {{ ref('mart_team_contracts') }}
group by 1, 2, 3
having count(*) > 1
