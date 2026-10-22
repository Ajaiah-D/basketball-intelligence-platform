"""The model's predictions: upcoming games, and the settled ones it is graded
on.

Nothing here imports ml: scikit-learn and scipy are dev-only and absent on
the deployed app, which once crashed with ModuleNotFoundError the moment a
real predictions table was published because this module imported
ml.evaluate. The few lines of metric math are duplicated below instead.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .core import objects_exist, q

# A probability at or above this is a home pick. A coin flip (exactly 0.5)
# counts as one, the same rule the page's cards and recent-results grid use.
HOME_PICK_THRESHOLD = 0.5

# The predictions graded against what happened: the earliest prediction per
# game only (grading a later re-run would let a model be scored on a
# prediction made after the result was known), joined to the result. dbt's
# mart_settled_predictions is the same query, and ml/evaluate.py reads that
# model; the dashboard keeps its own copy until a warehouse with the model
# is published, and tests/test_settled_predictions.py fails if the two ever
# differ.
SETTLED_PREDICTIONS_SQL = """
with first_prediction as (
    select
        *,
        row_number() over (
            partition by game_id order by predicted_at, prediction_id
        ) as attempt
    from main.predictions
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
join main_marts.fct_team_game f on f.game_id = p.game_id
where p.attempt = 1
  -- A cancelled game recorded as a 0-0 final is not a result: grading it
  -- would put a miss on the public track record for a game that never
  -- happened. Same exclusion as mart_game_features and ml/predict.py.
  and not (f.home_points = 0 and f.away_points = 0)
"""

_SETTLED_COLUMNS = [
    "game_id",
    "model_version",
    "game_date",
    "predicted_margin",
    "win_probability",
    "margin",
    "home_won",
    "home_points",
    "away_points",
]

_RECENT_COLUMNS = [
    "game_date",
    "home",
    "away",
    "home_pts",
    "away_pts",
    "win_probability",
    "predicted_margin",
    "correct",
]


def predictions_available() -> bool:
    """Whether the predictions table exists. It only does once ml/predict.py
    (or load_to_duckdb's history load) has run; the page shows a notice on a
    warehouse published before that."""
    return objects_exist("main.predictions")


def upcoming_predictions(limit: int = 30) -> pd.DataFrame:
    """The most recent prediction for each not-yet-played game, soonest first."""
    return q(
        """
        with latest as (
            select
                *,
                row_number() over (
                    partition by game_id order by predicted_at desc, prediction_id
                ) as recency
            from main.predictions
        )

        select
            l.game_id,
            l.game_date,
            s.tipoff_utc,
            l.win_probability,
            l.predicted_margin,
            s.home_team_abbreviation,
            s.away_team_abbreviation
        from latest l
        join main_staging.stg_schedule s on s.game_id = l.game_id
        where l.recency = 1 and s.game_status = 1
        order by l.game_date, l.game_id
        limit ?
        """,
        (limit,),
    )


def settled_predictions() -> pd.DataFrame:
    """Every graded prediction (SETTLED_PREDICTIONS_SQL), by game. Empty when
    the warehouse predates the predictions table or the game fact."""
    if not objects_exist("main.predictions", "main_marts.fct_team_game"):
        return pd.DataFrame(columns=_SETTLED_COLUMNS)
    # Sorted here rather than in the SQL, which has to stay the model's
    # query word for word.
    return q(SETTLED_PREDICTIONS_SQL).sort_values("game_id", ignore_index=True)


def prediction_track_record() -> dict:
    """The model's public accuracy record: accuracy, Brier score, margin
    MAE and n - the numbers ml.evaluate.track_record() logs, computed here
    because the dashboard can't import ml (see the module docstring).
    {"n": 0} when nothing has settled yet."""
    settled = settled_predictions()
    if settled.empty:
        return {"n": 0}

    home_won = settled["home_won"].astype(bool).to_numpy()
    win_probability = settled["win_probability"].astype(float).to_numpy()
    predicted_margin = settled["predicted_margin"].astype(float).to_numpy()
    margin = settled["margin"].astype(float).to_numpy()
    return {
        "accuracy": float(((win_probability >= HOME_PICK_THRESHOLD) == home_won).mean()),
        "brier": float(np.mean((win_probability - home_won.astype(float)) ** 2)),
        "margin_mae": float(np.mean(np.abs(predicted_margin - margin))),
        "n": len(settled),
    }


def recent_settled_predictions(n: int = 20) -> pd.DataFrame:
    """The latest graded predictions, newest first: who played, the final
    score, what the model said and whether it called the winner. Empty when
    nothing has settled (or the warehouse predates the tables it needs)."""
    if not objects_exist(
        "main.predictions", "main_marts.fct_team_game", "main_staging.stg_schedule"
    ):
        return pd.DataFrame(columns=_RECENT_COLUMNS)
    # The settled query goes in as a subquery, so the grid grades exactly
    # the games the track record does.
    df = q(
        f"""
        select
            s.game_date,
            s.home_team_abbreviation as home,
            s.away_team_abbreviation as away,
            t.home_points            as home_pts,
            t.away_points            as away_pts,
            t.win_probability,
            t.predicted_margin,
            (t.win_probability >= ?) = t.home_won as correct
        from ({SETTLED_PREDICTIONS_SQL}) t
        join main_staging.stg_schedule s on s.game_id = t.game_id
        order by s.game_date desc, t.game_id
        limit ?
        """,
        (HOME_PICK_THRESHOLD, n),
    )
    df["correct"] = df["correct"].astype(bool)
    return df
