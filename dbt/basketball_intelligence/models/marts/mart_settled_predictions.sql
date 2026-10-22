-- The predictions graded against what happened: one row per played game
-- that has a prediction, the earliest one. Later re-runs for the same game
-- exist in main.predictions, but grading the latest would let a model be
-- scored on a prediction made after the result was known. ml/evaluate.py
-- scores this model, and the dashboard's track record reads the same query
-- (dashboard/lib/data/predictions.py keeps a copy until a warehouse with
-- this model is published; tests/test_settled_predictions.py fails if the
-- two differ).
--
-- A view, unlike the other marts: ml/predict.py appends to main.predictions
-- after dbt has run, and ml/evaluate.py grades straight after that, so a
-- table built here would already be a run behind.
--
-- main.predictions only exists once load_to_duckdb.py has loaded the
-- history (or ml/predict.py has run). Without it the view is built empty,
-- with the same columns, rather than failing the whole build: the refresh
-- treats "nothing to grade yet" as a normal state. That empty view stays
-- empty until the next dbt build even if main.predictions appears later;
-- the refresh never hits this, since load_to_duckdb.py loads the committed
-- history before dbt runs. Empty is also normal
-- before the season's first result, so assert_marts_not_empty leaves this
-- model out.

{{ config(materialized='view') }}

{%- set predictions = source('ml', 'predictions') %}

{% if execute and load_relation(predictions) is none -%}

select
    cast(null as varchar) as game_id,
    cast(null as varchar) as model_version,
    cast(null as date)    as game_date,
    cast(null as double)  as predicted_margin,
    cast(null as double)  as win_probability,
    f.margin,
    f.home_won,
    f.home_points,
    f.away_points
from {{ ref('fct_team_game') }} f
where false

{%- else -%}

with first_prediction as (
    select
        *,
        row_number() over (
            partition by game_id order by predicted_at, prediction_id
        ) as attempt
    from {{ predictions }}
)

select
    p.game_id,
    p.model_version,
    p.game_date,
    p.predicted_margin,
    p.win_probability,
    f.margin,
    f.home_won,
    f.home_points,
    f.away_points
from first_prediction p
join {{ ref('fct_team_game') }} f on f.game_id = p.game_id
where p.attempt = 1
  -- A cancelled game recorded as a 0-0 final is not a result: grading it
  -- would put a miss on the public track record for a game that never
  -- happened. Same exclusion as mart_game_features and ml/predict.py.
  and not (f.home_points = 0 and f.away_points = 0)

{%- endif %}
