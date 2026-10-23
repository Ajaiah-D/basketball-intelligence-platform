-- player_pctile(column, best): the percentile of one player stat among
-- that season's qualified players, as one select-list column named
-- <column>_pctile, with no trailing comma.
--
-- Contract: call it in a select over a relation that has `season`, a
-- boolean `is_qualified` and the stat. `best` is 'high' or 'low', whichever
-- end of the stat is better; the best qualified player is percentile 100.
--
-- The percentile is 100 * percent_rank() among the qualified players who
-- have a value that season, so a player the leaderboard would not show
-- never moves anyone else's grade. A player outside that set - not
-- qualified, or missing the stat - gets null: he was not graded, which
-- says nothing about where he would have landed. The partition on the
-- "is graded" flag keeps the ungraded rows out of the ranked set.
{% macro player_pctile(column, best) %}
    {%- if best == 'high' -%}
        {%- set direction = 'asc' -%}
    {%- elif best == 'low' -%}
        {%- set direction = 'desc' -%}
    {%- else -%}
        {{ exceptions.raise_compiler_error("player_pctile: best must be 'high' or 'low', got '" ~ best ~ "'") }}
    {%- endif -%}
    case when is_qualified and {{ column }} is not null
         then round(100 * percent_rank() over (
             partition by season, (is_qualified and {{ column }} is not null)
             order by {{ column }} {{ direction }}), 1)
         end as {{ column }}_pctile
{%- endmacro %}
