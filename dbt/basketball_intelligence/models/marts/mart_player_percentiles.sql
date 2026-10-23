-- One row per player per season: the stats the player scatter and compare
-- views grade, each with a 0-100 percentile among that season's qualified
-- players (100 = best). Everything is read from mart_player_season, so the
-- values are the same numbers the rest of the site shows.
--
-- Qualified mirrors dashboard/lib/stats.py::qualification_threshold: the
-- threshold is 60% of the most games anyone played that season (rounded
-- down), at least 1 and at most 25, so early in a live season the cut
-- scales with the schedule instead of emptying every leaderboard. The
-- rule lives in the qualification_games macro; the Python function and the
-- macro must agree, which tests/test_player_percentiles.py and
-- assert_qualification_games_rule check. Players below it keep their row
-- and their values, with null percentiles and is_qualified = false.
--
-- Turnover rate is the one stat graded the other way: a lower rate is a
-- better percentile (see the player_pctile macro). A stat the box scores
-- cannot give (early seasons) is null, and so is its percentile.

with season_stats as (
    select
        *,
        {{ qualification_games('max(games_played) over (partition by season)') }}
            as qualification_games
    from {{ ref('mart_player_season') }}
),

flagged as (
    select
        *,
        games_played >= qualification_games as is_qualified
    from season_stats
)

select
    season,
    player_id,
    player_name,
    team_abbreviation,
    team_label,
    games_played,
    minutes,
    qualification_games,
    is_qualified,

    points_per_game,
    {{ player_pctile('points_per_game', 'high') }},
    true_shooting_pct,
    {{ player_pctile('true_shooting_pct', 'high') }},
    rebounds_per_game,
    {{ player_pctile('rebounds_per_game', 'high') }},
    assists_per_game,
    {{ player_pctile('assists_per_game', 'high') }},
    steals_per_game,
    {{ player_pctile('steals_per_game', 'high') }},
    blocks_per_game,
    {{ player_pctile('blocks_per_game', 'high') }},
    threes_made_per_game,
    {{ player_pctile('threes_made_per_game', 'high') }},
    turnover_pct,
    {{ player_pctile('turnover_pct', 'low') }},
    usage_pct,
    {{ player_pctile('usage_pct', 'high') }},
    assist_pct,
    {{ player_pctile('assist_pct', 'high') }},
    rebound_pct,
    {{ player_pctile('rebound_pct', 'high') }},
    offensive_rebound_pct,
    {{ player_pctile('offensive_rebound_pct', 'high') }},
    defensive_rebound_pct,
    {{ player_pctile('defensive_rebound_pct', 'high') }},
    steal_pct,
    {{ player_pctile('steal_pct', 'high') }},
    block_pct,
    {{ player_pctile('block_pct', 'high') }},
    free_throw_rate,
    {{ player_pctile('free_throw_rate', 'high') }}
from flagged
