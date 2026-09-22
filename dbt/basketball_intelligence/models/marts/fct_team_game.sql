-- One row per game, oriented home versus away.
--
-- A handful of neutral-site games (NBA Cup, international) list BOTH teams
-- with '@' in the matchup string, so picking the home team by 'vs.' alone
-- drops them entirely. Rank instead: the true home side ranks first when
-- one exists, and neutral games still produce exactly one deterministic
-- row, flagged as neutral.
--
-- is_neutral_site is true only when the source marks both sides away -
-- it misses games that were genuinely neutral-site but got a nominal
-- home team from the feed anyway, including the entire 2020 Orlando
-- bubble (88 games) and pre-2024-25 international games. Do not treat
-- this flag as "every neutral-site game"; see fct_team_game's model
-- description in _marts_models.yml for the exact gap.

with ranked as (
    select
        *,
        row_number() over (
            partition by game_id
            order by (matchup like '%vs.%') desc, team_id
        ) as side,
        count(*) filter (where matchup like '%vs.%') over (
            partition by game_id
        ) = 0 as is_neutral_site
    from {{ ref('int_team_game_opponent') }}
)

select
    season,
    game_id,
    game_date,
    is_neutral_site,
    team_id                  as home_team_id,
    team_abbreviation        as home_team_abbreviation,
    opp_team_id              as away_team_id,
    opp_team_abbreviation    as away_team_abbreviation,
    points                   as home_points,
    opp_points               as away_points,
    points - opp_points      as margin,
    points > opp_points      as home_won,
    field_goals_attempted + 0.44 * free_throws_attempted
        - offensive_rebounds + turnovers          as home_possessions
from ranked
where side = 1
