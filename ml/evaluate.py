"""Score settled predictions against what actually happened.

Only the earliest prediction per game counts. Later re-runs for the same
game exist in the table, but grading the latest one would let a model be
scored on a prediction made after the result was known.
"""

from __future__ import annotations

import pandas as pd

from ml.train import evaluate

SETTLED_SQL = """
with first_prediction as (
    select *, row_number() over (
        partition by game_id order by predicted_at
    ) as attempt
    from predictions
)
select p.game_id, p.model_version, p.game_date, p.predicted_margin,
       p.win_probability, f.margin, f.home_won
from first_prediction p
join main_marts.fct_team_game f on f.game_id = p.game_id
where p.attempt = 1
  -- Same no-contest exclusion as mart_game_features.sql, ml/features.py
  -- and ml/predict.py: a cancelled game recorded as a 0-0 final is not a
  -- result. Without this, a real pre-tipoff prediction for a game that
  -- never happened would be graded as a definite miss against a 0 actual
  -- margin, quietly penalizing the public track record for it.
  and not (f.home_points = 0 and f.away_points = 0)
"""


def settled_predictions(con) -> pd.DataFrame:
    return con.execute(SETTLED_SQL).df()


def track_record(con) -> dict:
    settled = settled_predictions(con)
    if settled.empty:
        return {"n": 0}
    return evaluate(settled)


def calibration_table(con, bins: int = 10) -> pd.DataFrame:
    """Predicted probability against observed frequency, for a reliability plot."""
    settled = settled_predictions(con)
    if settled.empty:
        return pd.DataFrame(columns=["bucket", "predicted", "observed", "n"])
    settled["bucket"] = (settled["win_probability"] * bins).astype(int).clip(0, bins - 1)
    return settled.groupby("bucket").agg(
        predicted=("win_probability", "mean"),
        observed=("home_won", "mean"),
        n=("game_id", "size"),
    ).reset_index()


if __name__ == "__main__":
    from pathlib import Path

    import duckdb

    # predictions and/or the marts it joins against may not exist yet (a
    # fresh warehouse, or a week where ml.predict wrote nothing because the
    # slate was empty) - that is a normal state, not a failure, so a missing
    # table degrades to "nothing to score" instead of crashing the refresh.
    db_path = Path(__file__).resolve().parent.parent / "warehouse" / "basketball.duckdb"
    con = duckdb.connect(str(db_path))
    try:
        try:
            record = track_record(con)
        except duckdb.CatalogException:
            # The real "table doesn't exist yet" condition. A
            # BinderException from schema drift, a ConversionException, or
            # an IOException must still surface as a real error rather
            # than silently reading as "nothing to score".
            record = {"n": 0}

        if record["n"] == 0:
            print("No settled predictions to score yet.")
        else:
            print(
                f"Scored {record['n']} settled predictions: "
                f"accuracy={record['accuracy']:.3f} brier={record['brier']:.3f} "
                f"margin_mae={record['margin_mae']:.1f}"
            )
    finally:
        con.close()
