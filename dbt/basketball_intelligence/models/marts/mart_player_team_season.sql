-- One row per player per team per season: the season line over only the
-- games a player played for that team. A player traded mid-season gets a
-- row for each stint, and the stints add back up to his mart_player_season
-- row. This is what a team's roster shows - filing a traded player's whole
-- season under his last team would credit the old team's games to the new
-- one.

select
    season,
    player_id,
    any_value(player_name)  as player_name,
    team_id,
    team_abbreviation,
    min(game_date)          as first_game,
    count(*)                as games_played,
    {{ player_stat_line() }}
from {{ ref('stg_player_game_logs') }}
group by season, player_id, team_id, team_abbreviation
