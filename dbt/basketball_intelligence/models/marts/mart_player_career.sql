-- One row per player, pooled across every ingested season. Averages and
-- percentages come from the career's game rows directly, not from averaging
-- season lines, so a short season weighs only as much as its games.
--
-- A handful of players are spelled differently in different seasons
-- (Valančiūnas lost his accents in 2025-26, Bobby Portis gained a Jr.);
-- the name and team shown are the most recent ones.

select
    player_id,
    max_by(player_name, game_date)         as player_name,
    -- Ties on the date broken by team code, as in mart_player_season
    max_by(team_abbreviation, (game_date, team_abbreviation)) as team,
    count(distinct season)                 as seasons,
    min(season)                            as first_season,
    max(season)                            as last_season,
    count(*)                               as games_played,
    cast(max(points) as int)               as career_high,
    cast(sum(points) as int)               as pts_total,
    cast(sum(case when is_win then 1 else 0 end) as int) as wins,
    {{ player_stat_line() }}
from {{ ref('stg_player_game_logs') }}
group by player_id
