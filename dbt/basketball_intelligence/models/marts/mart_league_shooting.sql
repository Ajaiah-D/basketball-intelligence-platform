-- One row per season: league-wide shooting percentages, weighted by volume
-- (every make over every attempt, not an average of player percentages,
-- which would let a 1-for-1 bench player count as much as a starter). The
-- benchmark a player's percentages are compared against.
--
-- Only games that record both the makes and the attempts count, as in the
-- player marts: early seasons often have one without the other, which put
-- the 1979-80 league at 33.4% from three instead of 28.6%.

select
    season,
    {{ shooting_pct('field_goals_made', 'field_goals_attempted') }}       as fg_pct,
    {{ shooting_pct('three_pointers_made', 'three_pointers_attempted') }} as fg3_pct,
    {{ shooting_pct('free_throws_made', 'free_throws_attempted') }}       as ft_pct
from {{ ref('stg_player_game_logs') }}
group by season
