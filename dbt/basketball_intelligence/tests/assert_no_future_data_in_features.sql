-- Recompute features from scratch with an explicit date filter and compare.
-- If the window frames in mart_game_features ever stop excluding the current
-- row, the stored value starts including the game's own result and these
-- diverge. Sampled to keep the test cheap.
--
-- The re-derivations deliberately share no machinery with the model: no
-- window function, no shared CTE, just correlated aggregates over an
-- explicit "strictly before this game's date" filter. That is what makes
-- this an independent check rather than a restatement of the same SQL.
--
-- Three features are checked, chosen to cover the distinct ways the model
-- could leak rather than to cover every column:
--   home_season_margin - the unbounded frame w, home side.
--   away_season_margin - the away side, produced by the long CTE's second
--                        branch and joined on "not at_home". Nothing else
--                        here would notice if that side alone broke.
--   home_last5_margin  - a BOUNDED frame (w5). The unbounded frame passing
--                        says nothing about whether w5 and w10 exclude the
--                        current row; they are separate frame definitions
--                        and can break independently.
--
-- Each re-derivation must reproduce what the model actually stores: a team's
-- average margin over ALL its prior games that season, home and away, with
-- the sign flipped for its away games. Averaging only its home games would
-- be a different quantity, so the test would fail on correct data and tell
-- us nothing about leakage.
--
-- The no-contest exclusion is repeated here because the comparison is
-- against fct_team_game directly, not through the model's valid_games CTE.

with sample as (
    -- The filter goes in an inner select: USING SAMPLE applied alongside a
    -- sibling WHERE samples the table before the filter, which would leave
    -- far fewer than 500 rows to check. Both sides need at least 5 prior
    -- games so every check below is well defined and a null re-derivation
    -- is a real failure rather than an expected cold start.
    select * from (
        select * from {{ ref('mart_game_features') }}
        where home_games_played >= 5
          and away_games_played >= 5
          and season >= '2015-16'
    ) using sample 500 rows
),

valid_games as (
    select * from {{ ref('fct_team_game') }}
    where not (home_points = 0 and away_points = 0)
),

checks as (
    select
        'home_season_margin' as feature,
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

    union all

    select
        'away_season_margin',
        s.game_id,
        s.away_season_margin,
        (select avg(case when f.home_team_id = s.away_team_id
                         then f.margin
                         else -f.margin end)
         from valid_games f
         where f.season = s.season
           and (f.home_team_id = s.away_team_id
                or f.away_team_id = s.away_team_id)
           and f.game_date < s.game_date)
    from sample s

    union all

    select
        'home_last5_margin',
        s.game_id,
        s.home_last5_margin,
        -- The 5 most recent prior games: what "rows between 5 preceding and
        -- 1 preceding" means once the rows are ordered by game_date, game_id.
        (select avg(recent.team_margin)
         from (
             select case when f.home_team_id = s.home_team_id
                         then f.margin
                         else -f.margin end as team_margin
             from valid_games f
             where f.season = s.season
               and (f.home_team_id = s.home_team_id
                    or f.away_team_id = s.home_team_id)
               and f.game_date < s.game_date
             order by f.game_date desc, f.game_id desc
             limit 5
         ) recent)
    from sample s
)

select feature, game_id, stored, independent
from checks
where independent is null
   or abs(stored - independent) > 0.001
