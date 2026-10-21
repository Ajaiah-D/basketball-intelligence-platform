-- player_stat_line(): the season line every player mart shares.
--
-- Contract: call it in the select list of a query over
-- stg_player_game_logs rows (or rows carrying the same column names) that
-- is grouped at any grain - a season, one team stint, a career. It emits
-- these aggregate columns, with no leading or trailing comma:
--   minutes_per_game, points_per_game, rebounds_per_game, assists_per_game,
--   steals_per_game, blocks_per_game, threes_made_per_game, fga_per_game,
--   three_pa_per_game, fta_per_game, plus_minus_per_game, fga_total,
--   tpa_total, fta_total, fg_pct, fg3_pct, ft_pct, true_shooting_pct,
--   assist_to_turnover, shot_poss.
-- mart_player_season, mart_player_team_season and mart_player_career all
-- call it, so their definitions can't drift apart.
--
-- The definitions are the dashboard's (dashboard/lib/db.py), kept expression
-- for expression - including dividing before the * 100 - so the values
-- round identically, with one correction to the shooting percentages:
--   - averages are avg(stat), which skips a game whose stat is null. The
--     source has whole columns missing in early seasons; counting those
--     games as zeros would understate the player.
--   - percentages (shooting_pct below) are summed makes over summed
--     attempts, counting only games where both are recorded, and null with
--     no attempts. Before 1985-86 the source often has the makes but not
--     the attempts; summing each side over its own games put 1980-81
--     seasons at 1080% from the field.
--   - true shooting is withheld when any game in the group has a null
--     field_goals_attempted, free_throws_attempted or points. sum() skips
--     nulls, so one such game would add its points to the numerator and
--     nothing to the denominator (Jim Brewer's 1979-80 came out at 78.1%).
--     This is narrower than mart_player_season's box_score_complete, which
--     also needs team and opponent columns true shooting does not use.

{% macro player_stat_line() %}
        round(avg(minutes_played), 1)            as minutes_per_game,
        round(avg(points), 1)                    as points_per_game,
        round(avg(total_rebounds), 1)            as rebounds_per_game,
        round(avg(assists), 1)                   as assists_per_game,
        round(avg(steals), 1)                    as steals_per_game,
        round(avg(blocks), 1)                    as blocks_per_game,
        round(avg(three_pointers_made), 1)       as threes_made_per_game,
        round(avg(field_goals_attempted), 1)     as fga_per_game,
        round(avg(three_pointers_attempted), 1)  as three_pa_per_game,
        round(avg(free_throws_attempted), 1)     as fta_per_game,
        round(avg(plus_minus), 1)                as plus_minus_per_game,
        cast(sum(field_goals_attempted) as int)     as fga_total,
        cast(sum(three_pointers_attempted) as int)  as tpa_total,
        cast(sum(free_throws_attempted) as int)     as fta_total,
        {{ shooting_pct('field_goals_made', 'field_goals_attempted') }}     as fg_pct,
        {{ shooting_pct('three_pointers_made', 'three_pointers_attempted') }} as fg3_pct,
        {{ shooting_pct('free_throws_made', 'free_throws_attempted') }}     as ft_pct,
        case when count(*) filter (
                 where field_goals_attempted is null
                    or free_throws_attempted is null
                    or points is null) > 0
             then null
             else round(sum(points) / nullif(2 * (sum(field_goals_attempted)
                  + 0.44 * sum(free_throws_attempted)), 0) * 100, 1)
        end                                      as true_shooting_pct,
        round(sum(assists) / nullif(sum(turnovers), 0), 2) as assist_to_turnover,
        -- Shooting possessions: the weight for averaging true shooting
        -- across groups (a games-played weight would count a low-volume
        -- year the same as a high-volume one).
        sum(field_goals_attempted) + 0.44 * sum(free_throws_attempted) as shot_poss
{% endmacro %}

-- shooting_pct(made, attempted): made / attempted x 100 to 1 decimal over
-- the group's games that record both, null with no attempts. An aggregate
-- expression; mart_league_shooting uses it too.
{% macro shooting_pct(made, attempted) -%}
round(sum({{ made }}) filter (where {{ made }} is not null and {{ attempted }} is not null)
        / nullif(sum({{ attempted }}) filter (where {{ made }} is not null and {{ attempted }} is not null), 0)
        * 100, 1)
{%- endmacro %}
