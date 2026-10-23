-- qualification_games(max_gp): the games a player needs to qualify for a
-- leaderboard in a season where the most games anyone played is `max_gp`
-- (a SQL expression).
--
-- Mirrors dashboard/lib/stats.py::qualification_threshold: 60% of the most
-- games played, rounded down (stats.py takes int() of a positive product,
-- which is floor()), at least 1 and at most 25, so early in a live season
-- the cut scales with the schedule. Every finished season is at the 25 cap,
-- so the scaled branch only runs in a live season;
-- assert_qualification_games_rule applies this same macro to made-up season
-- lengths so that branch is tested without waiting for one.
{% macro qualification_games(max_gp) -%}
    greatest(1, least(25, cast(floor(({{ max_gp }}) * 0.6) as int)))
{%- endmacro %}
