-- One row per player per team-season: what the team paid him that season,
-- where that ranks on its payroll, and his share of the total. Feeds the
-- Finances page's "biggest contracts" list - the answer to "why is this team
-- over the tax" that a payroll total alone can't give.
with lines as (
    select
        season,
        team_abbreviation,
        bbref_player_id,
        any_value(player) as player,
        sum(salary_usd)   as salary_usd
    from {{ ref('stg_team_payroll_players') }}
    group by 1, 2, 3
)

select
    season,
    team_abbreviation,
    bbref_player_id,
    player,
    salary_usd,
    row_number() over (partition by season, team_abbreviation
                       order by salary_usd desc, player) as salary_rank,
    round(salary_usd / sum(salary_usd) over (partition by season, team_abbreviation), 4)
                                                         as share_of_payroll
from lines
