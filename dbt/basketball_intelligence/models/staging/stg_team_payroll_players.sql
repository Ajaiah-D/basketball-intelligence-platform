-- One row per salary line on a team's Basketball-Reference season page,
-- typed. A player can appear twice for one team-season (two 10-day
-- contracts); mart_team_contracts sums those.
select
    cast(season as varchar)            as season,
    cast(team_abbreviation as varchar) as team_abbreviation,
    cast(bbref_player_id as varchar)   as bbref_player_id,
    cast(player as varchar)            as player,
    cast(salary_usd as bigint)         as salary_usd,
    cast(fetched_at_utc as timestamp)  as fetched_at_utc
from {{ source('raw', 'team_payroll_players') }}
