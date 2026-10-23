-- Every mart must have rows. Most tests here select the bad rows of a
-- model, so an empty model passes all of them: a join that stops matching
-- or a filter that drops everything would publish an empty page with a
-- green build. This is the check that notices.
--
-- mart_team_finances must also have rows for the newest payroll season.
-- stg_team_payroll has that season, so an empty mart season means the
-- mart's join broke (most likely the season lost its salary_cap_history
-- row to the inner join), not that the scrape failed: a scrape that fails
-- outright never writes a new season, so the newest season stays the last
-- complete one. Partial coverage of that season is a different matter -
-- the payroll step is non-fatal by design, and the refresh only scrapes
-- teams that have played - so it only warns, in
-- assert_payroll_covers_every_team.

with counts as (
    select 'fct_team_game' as model, count(*) as row_count from {{ ref('fct_team_game') }}
    union all
    select 'mart_game_features', count(*) from {{ ref('mart_game_features') }}
    union all
    select 'mart_league_shooting', count(*) from {{ ref('mart_league_shooting') }}
    union all
    select 'mart_player_career', count(*) from {{ ref('mart_player_career') }}
    union all
    select 'mart_player_defense', count(*) from {{ ref('mart_player_defense') }}
    union all
    select 'mart_player_percentiles', count(*) from {{ ref('mart_player_percentiles') }}
    union all
    select 'mart_player_season', count(*) from {{ ref('mart_player_season') }}
    union all
    select 'mart_player_team_season', count(*) from {{ ref('mart_player_team_season') }}
    union all
    select 'mart_team_contracts', count(*) from {{ ref('mart_team_contracts') }}
    union all
    select 'mart_team_finances', count(*) from {{ ref('mart_team_finances') }}
    union all
    select 'mart_team_profile', count(*) from {{ ref('mart_team_profile') }}
    union all
    select 'mart_team_season', count(*) from {{ ref('mart_team_season') }}
    union all
    select 'mart_team_standings', count(*) from {{ ref('mart_team_standings') }}
),

newest_payroll as (
    select max(season) as season from {{ ref('stg_team_payroll') }}
)

select model, 'no rows' as problem
from counts
where row_count = 0

union all

select
    'mart_team_finances',
    n.season || ': no rows, though stg_team_payroll has the season'
from newest_payroll n
where n.season is not null
  and not exists (
      select 1 from {{ ref('mart_team_finances') }} f where f.season = n.season
  )
