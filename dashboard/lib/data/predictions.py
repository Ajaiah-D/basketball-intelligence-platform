"""The model's predictions: upcoming games, and the settled ones it is graded
on.

The grading itself (each game's first prediction beside its result, the
no-contest game left out) is dbt's mart_settled_predictions, which
ml/evaluate.py reads too. Nothing here imports ml: scikit-learn and scipy
are dev-only and absent on the deployed app, which once crashed with
ModuleNotFoundError the moment a real predictions table was published
because this module imported ml.evaluate. The track record's three
averages are taken in SQL over the mart's rows instead;
tests/test_settled_predictions.py checks they give ml's numbers.
"""

from __future__ import annotations

import pandas as pd

from core.constants import HOME_PICK_THRESHOLD

from .core import objects_exist, q

# The most recent prediction for each game: a game is re-predicted every
# day until it tips off, and the latest run has the freshest inputs.
# Upcoming games and the Schedule page both read it.
LATEST_PREDICTIONS_SQL = """
select *
from (
    select
        *,
        row_number() over (
            partition by game_id order by predicted_at desc, prediction_id
        ) as recency
    from main.predictions
)
where recency = 1
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
        f"""
        select
            l.game_id,
            l.game_date,
            s.tipoff_utc,
            l.win_probability,
            l.predicted_margin,
            s.home_team_abbreviation,
            s.away_team_abbreviation
        from ({LATEST_PREDICTIONS_SQL}) l
        join main_staging.stg_schedule s on s.game_id = l.game_id
        where s.game_status = 1
        order by l.game_date, l.game_id
        limit ?
        """,
        (limit,),
    )


def latest_predictions() -> pd.DataFrame:
    """The latest prediction for every game ever predicted, played or not:
    game_id, win_probability (home) and predicted_margin (home). Empty on a
    warehouse without the predictions table."""
    if not predictions_available():
        return pd.DataFrame(columns=["game_id", "win_probability", "predicted_margin"])
    return q(
        f"""
        select game_id, win_probability, predicted_margin
        from ({LATEST_PREDICTIONS_SQL})
        order by game_id
        """
    )


def settled_available() -> bool:
    """Whether the warehouse has the graded predictions. A warehouse
    published before mart_settled_predictions existed lacks them; the page
    shows a notice for the track record instead."""
    return objects_exist("main_marts.mart_settled_predictions")


def settled_predictions() -> pd.DataFrame:
    """Every graded prediction (mart_settled_predictions), by game. Empty
    when the warehouse predates the mart."""
    if not settled_available():
        return pd.DataFrame(columns=_SETTLED_COLUMNS)
    return q(
        """
        select
            game_id,
            model_version,
            game_date,
            predicted_margin,
            win_probability,
            margin,
            home_won,
            home_points,
            away_points
        from main_marts.mart_settled_predictions
        order by game_id
        """
    )


def prediction_track_record() -> dict:
    """The model's public accuracy record: accuracy, Brier score, margin
    MAE and n - the numbers ml.evaluate.track_record() logs, averaged here
    over the mart's rows because the dashboard can't import ml (see the
    module docstring). A coin flip counts as a home pick
    (HOME_PICK_THRESHOLD). {"n": 0} when nothing has settled yet."""
    if not settled_available():
        return {"n": 0}
    record = q(
        """
        select
            count(*) as n,
            count_if((win_probability >= ?) = home_won) / count(*) as accuracy,
            avg(power(win_probability - home_won::double, 2)) as brier,
            avg(abs(predicted_margin - margin)) as margin_mae
        from main_marts.mart_settled_predictions
        """,
        (HOME_PICK_THRESHOLD,),
    ).iloc[0]
    n = int(record["n"])
    if n == 0:
        return {"n": 0}
    return {
        "accuracy": float(record["accuracy"]),
        "brier": float(record["brier"]),
        "margin_mae": float(record["margin_mae"]),
        "n": n,
    }


def recent_settled_predictions(n: int = 20) -> pd.DataFrame:
    """The latest graded predictions, newest first: who played, the final
    score, what the model said and whether it called the winner. Empty when
    nothing has settled (or the warehouse predates the tables it needs)."""
    if not objects_exist("main_marts.mart_settled_predictions", "main_staging.stg_schedule"):
        return pd.DataFrame(columns=_RECENT_COLUMNS)
    # The mart's rows, so the list grades exactly the games the track
    # record does, with the same coin-flip rule.
    df = q(
        """
        select
            s.game_date,
            s.home_team_abbreviation as home,
            s.away_team_abbreviation as away,
            t.home_points            as home_pts,
            t.away_points            as away_pts,
            t.win_probability,
            t.predicted_margin,
            (t.win_probability >= ?) = t.home_won as correct
        from main_marts.mart_settled_predictions t
        join main_staging.stg_schedule s on s.game_id = t.game_id
        order by s.game_date desc, t.game_id
        limit ?
        """,
        (HOME_PICK_THRESHOLD, n),
    )
    df["correct"] = df["correct"].astype(bool)
    return df
