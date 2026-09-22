-- One row per game with features known before tip-off.
--
-- Every window below excludes the current row. That exclusion is the whole
-- point: a feature that can see its own game's result makes the backtest
-- meaningless, and the error is invisible in the output. The singular test
-- assert_no_future_data_in_features re-derives a sample independently
-- rather than trusting the frames by eye.

with valid_games as (
    -- Excludes no-contest fixtures: Task 4 found one cancelled game
    -- recorded as a 0-0 final (game_id 0021201214, 2013-04-16 IND @ BOS,
    -- postponed after the Boston Marathon bombing). It never happened, so
    -- it must not feed anyone's rolling form or Elo. Filtered by score
    -- rather than by hardcoded game_id, since a future season could have
    -- another. Every reference to fct_team_game below goes through this
    -- CTE, not the model directly, so the exclusion can't be missed in
    -- one branch and not another.
    select * from {{ ref('fct_team_game') }}
    where not (home_points = 0 and away_points = 0)
),

long as (
    -- Back to two rows per game so each team's history is its own window.
    select game_id, season, game_date, home_team_id as team_id,
           away_team_id as opp_team_id, margin as team_margin,
           home_won as team_won, true as at_home
    from valid_games
    union all
    select game_id, season, game_date, away_team_id, home_team_id,
           -margin, not home_won, false
    from valid_games
),

team_form as (
    select
        game_id,
        team_id,
        at_home,
        count(*) over w                     as games_played_this_season,
        avg(team_margin) over w             as season_margin_avg,
        avg(case when team_won then 1.0 else 0.0 end) over w as season_win_pct,
        avg(team_margin) over w5            as last5_margin_avg,
        avg(team_margin) over w10           as last10_margin_avg,
        game_date - lag(game_date) over (
            partition by season, team_id order by game_date, game_id
        )                                   as days_rest
    from long
    window
        w as (partition by season, team_id order by game_date, game_id
              rows between unbounded preceding and 1 preceding),
        w5 as (partition by season, team_id order by game_date, game_id
               rows between 5 preceding and 1 preceding),
        w10 as (partition by season, team_id order by game_date, game_id
                rows between 10 preceding and 1 preceding)
)

select
    f.game_id,
    f.season,
    f.game_date,
    f.is_neutral_site,
    f.home_team_id,
    f.away_team_id,
    h.games_played_this_season          as home_games_played,
    a.games_played_this_season          as away_games_played,
    h.season_margin_avg                 as home_season_margin,
    a.season_margin_avg                 as away_season_margin,
    h.season_win_pct                    as home_season_win_pct,
    a.season_win_pct                    as away_season_win_pct,
    h.last5_margin_avg                  as home_last5_margin,
    a.last5_margin_avg                  as away_last5_margin,
    h.last10_margin_avg                 as home_last10_margin,
    a.last10_margin_avg                 as away_last10_margin,
    h.days_rest                         as home_days_rest,
    a.days_rest                         as away_days_rest,
    coalesce(h.days_rest = 1, false)    as home_back_to_back,
    coalesce(a.days_rest = 1, false)    as away_back_to_back,
    -- Targets. Never features.
    f.margin,
    f.home_won
from valid_games f
join team_form h on h.game_id = f.game_id and h.at_home
join team_form a on a.game_id = f.game_id and not a.at_home
