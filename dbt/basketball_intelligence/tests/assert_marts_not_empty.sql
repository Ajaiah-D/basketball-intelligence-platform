-- Every mart must have rows. Most tests here select the bad rows of a
-- model, so an empty model passes all of them: a join that stops matching
-- or a filter that drops everything would publish an empty page with a
-- green build. This is the check that notices.
--
-- mart_team_finances also has to cover the whole league in its newest
-- season, because the Finances page leads with that season's league
-- snapshot. "The whole league" is every team in that season's game logs
-- rather than a literal 30: the weekly refresh scrapes payroll for the
-- teams that have played so far, so in a season's opening week the newest
-- payroll season honestly has fewer than 30 rows, and a fixed 30 would
-- fail the refresh every October. For any season that has been played
-- through it is 30 (CI's fixtures: 2024-25), and a team whose payroll row
-- went missing, or a season that lost its salary_cap_history row to the
-- mart's inner join, fails here.

with counts as (
    select 'fct_team_game' as model, count(*) as row_count from {{ ref('fct_team_game') }}
    union all
    select 'mart_game_features', count(*) from {{ ref('mart_game_features') }}
    union all
    select 'mart_league_shooting', count(*) from {{ ref('mart_league_shooting') }}
    union all
    select 'mart_player_career', count(*) from {{ ref('mart_player_career') }}
    union all
    select 'mart_player_season', count(*) from {{ ref('mart_player_season') }}
    union all
    select 'mart_player_team_season', count(*) from {{ ref('mart_player_team_season') }}
    union all
    select 'mart_team_contracts', count(*) from {{ ref('mart_team_contracts') }}
    union all
    select 'mart_team_finances', count(*) from {{ ref('mart_team_finances') }}
    union all
    select 'mart_team_season', count(*) from {{ ref('mart_team_season') }}
    union all
    select 'mart_team_standings', count(*) from {{ ref('mart_team_standings') }}
),

newest_payroll as (
    select max(season) as season from {{ ref('stg_team_payroll') }}
),

league as (
    select
        n.season,
        (select count(distinct team_abbreviation)
         from {{ ref('mart_team_finances') }} f
         where f.season = n.season)                     as finance_teams,
        (select count(distinct team_abbreviation)
         from {{ ref('stg_team_game_logs') }} g
         where g.season = n.season)                     as teams_played
    from newest_payroll n
)

select model, 'no rows' as problem
from counts
where row_count = 0

union all

select
    'mart_team_finances',
    coalesce(season, 'no payroll season') || ': ' || finance_teams
        || ' teams, but ' || teams_played || ' played that season'
from league
where finance_teams <> teams_played
   or teams_played = 0
