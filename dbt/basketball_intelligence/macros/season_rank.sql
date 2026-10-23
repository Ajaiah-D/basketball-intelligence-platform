-- season_rank(column, best): the league rank and percentile of one team
-- stat within its season, as two select-list columns named
-- <column>_rank and <column>_pctile, with no trailing comma.
--
-- Contract: call it in a select over a relation that has a `season`
-- column and the stat. `best` is 'high' or 'low', whichever end of the
-- stat is better; the best team is rank 1 and percentile 100. For style
-- stats with no better end (pace, three-point rates) pass 'high', so rank
-- 1 means the most, not the best.
--
-- Ties share a rank (rank(), not row_number()), so two teams on the same
-- value never get different grades. The percentile is
--   100 * (1 - (rank - 1) / (teams with a value that season - 1))
-- counting only teams that have a value, so the last team always sits at
-- 0 even in a season where a few teams are missing the stat. A null value
-- gets a null rank and percentile, not last place: the stat was not
-- measured, which says nothing about how the team compares.
{% macro season_rank(column, best) %}
    {%- if best == 'high' -%}
        {%- set direction = 'desc' -%}
    {%- elif best == 'low' -%}
        {%- set direction = 'asc' -%}
    {%- else -%}
        {{ exceptions.raise_compiler_error("season_rank: best must be 'high' or 'low', got '" ~ best ~ "'") }}
    {%- endif -%}
    case when {{ column }} is null then null
         else rank() over (partition by season order by {{ column }} {{ direction }}) end
        as {{ column }}_rank,
    case when {{ column }} is null then null
         else round(100 * (1 - (rank() over (partition by season order by {{ column }} {{ direction }}) - 1)
            / nullif(count({{ column }}) over (partition by season) - 1, 0)), 1) end
        as {{ column }}_pctile
{%- endmacro %}
