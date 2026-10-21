"""Score settled predictions against what actually happened.

Only the earliest prediction per game counts. Later re-runs for the same
game exist in the table, but grading the latest one would let a model be
scored on a prediction made after the result was known.
"""

from __future__ import annotations

import logging
import sys

import pandas as pd

from core import paths
from ml.train import evaluate

log = logging.getLogger(__name__)

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
    return (
        settled.groupby("bucket")
        .agg(
            predicted=("win_probability", "mean"),
            observed=("home_won", "mean"),
            n=("game_id", "size"),
        )
        .reset_index()
    )


def main() -> None:
    """Log the track record of every settled prediction in the warehouse."""
    import duckdb

    # predictions and/or the marts it joins against may not exist yet (a
    # fresh warehouse, or a week where ml.predict wrote nothing because the
    # slate was empty) - that is a normal state, not a failure, so a missing
    # table degrades to "nothing to score" instead of crashing the refresh.
    db_path = paths.warehouse_path()
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
            log.info("No settled predictions to score yet.")
        else:
            log.info(
                "Scored %d settled predictions: accuracy=%.3f brier=%.3f margin_mae=%.1f",
                record["n"],
                record["accuracy"],
                record["brier"],
                record["margin_mae"],
            )
    finally:
        con.close()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )
    main()
