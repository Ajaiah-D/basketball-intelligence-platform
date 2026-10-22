{{ config(severity='warn') }}

-- The newest payroll season should have a mart_team_finances row for every
-- team that has played in it (30 once a season is under way). The Finances
-- page leads with that season's league snapshot, so a missing team is a
-- gap worth seeing.
--
-- A warning, not an error: the payroll scrape is non-fatal in the weekly
-- refresh (Basketball-Reference rate limits and layout changes must not
-- block the game data and predictions), and in a season's opening days
-- the refresh only scrapes the teams that have played. Failing dbt_build
-- here would turn exactly the outage the refresh avoids into a fatal one.
-- The refresh records the warning on its run line and health_check.py
-- prints it. A season with no rows at all is a broken join, not a partial
-- scrape, and fails assert_marts_not_empty instead.
--
-- "Every team that played" rather than a literal 30, so an expansion
-- season needs no edit here.

with newest_payroll as (
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

select season, finance_teams, teams_played
from league
where finance_teams > 0
  and finance_teams < teams_played
