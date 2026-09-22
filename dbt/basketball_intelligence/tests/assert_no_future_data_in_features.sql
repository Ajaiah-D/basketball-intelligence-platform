-- Recompute one feature from scratch with an explicit date filter and
-- compare. If the window frames in mart_game_features ever stop excluding
-- the current row, the stored value starts including the game's own result
-- and this diverges. Sampled to keep the test cheap.
--
-- The re-derivation deliberately shares no machinery with the model: no
-- window function, no shared CTE, just a correlated aggregate over an
-- explicit "strictly before this game's date" filter. That is what makes
-- it an independent check rather than a restatement of the same SQL.
--
-- It must re-derive the feature the model actually stores, which is the
-- home team's average margin over ALL its prior games this season, home
-- and away, with the sign flipped for away games. Averaging only its home
-- games would be a different quantity, so the test would fail on correct
-- data and tell us nothing about leakage.
--
-- The no-contest exclusion is repeated here because the comparison is
-- against fct_team_game directly, not through the model's valid_games CTE.

with sample as (
    -- The filter goes in an inner select: USING SAMPLE applied alongside a
    -- WHERE clause samples the table before the filter, which would leave
    -- far fewer than 500 rows to check.
    select * from (
        select * from {{ ref('mart_game_features') }}
        where home_games_played >= 5 and season >= '2015-16'
    ) using sample 500 rows
),

valid_games as (
    select * from {{ ref('fct_team_game') }}
    where not (home_points = 0 and away_points = 0)
),

recomputed as (
    select
        s.game_id,
        s.home_season_margin as stored,
        (select avg(case when f.home_team_id = s.home_team_id
                         then f.margin
                         else -f.margin end)
         from valid_games f
         where f.season = s.season
           and (f.home_team_id = s.home_team_id
                or f.away_team_id = s.home_team_id)
           and f.game_date < s.game_date) as independent
    from sample s
)

select game_id, stored, independent
from recomputed
where independent is null
   or abs(stored - independent) > 0.001
