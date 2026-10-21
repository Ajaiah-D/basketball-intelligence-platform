-- mart_player_season inner-joins each player game to his team's and the
-- opponent's game logs for the advanced-rate context. A game with no
-- matching team row would vanish from the player's season - his averages,
-- totals and games played quietly computed over fewer games, or the
-- season dropped altogether - and the dashboard reads its season lines
-- from this mart. So the mart must hold exactly one row per season-player
-- in the game logs, each with every game counted. Any row here is a
-- season-player missing from one side, or a games_played mismatch.
--
-- Up to 50 rows warn rather than fail. One anomalous game in the feed (a
-- box score with no team-log row) puts every player in it here, about 20
-- rows (dropping one team row from a 2024-25 game gave 19), and failing
-- the weekly refresh over that would leave the whole site a week stale for
-- one game's averages; the WARN still shows in the run's dbt_build.log.
-- Past 50 - more than two such games - it is a systemic join or ingestion
-- fault, and the build fails.
{{ config(severity='error', warn_if='>0', error_if='>50') }}

with logs as (
    select season, player_id, count(*) as log_games
    from {{ ref('stg_player_game_logs') }}
    group by season, player_id
),

mart as (
    select season, player_id, games_played as mart_games
    from {{ ref('mart_player_season') }}
)

select
    coalesce(l.season, m.season)        as season,
    coalesce(l.player_id, m.player_id)  as player_id,
    l.log_games,
    m.mart_games
from logs l
full outer join mart m
  on m.season = l.season
 and m.player_id = l.player_id
where l.player_id is null
   or m.player_id is null
   or l.log_games <> m.mart_games
