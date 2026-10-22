"""Score settled predictions against what actually happened.

Only the earliest prediction per game counts. Later re-runs for the same
game exist in the table, but grading the latest one would let a model be
scored on a prediction made after the result was known. That rule lives in
dbt's mart_settled_predictions, which this reads.
"""

from __future__ import annotations

import logging
import sys

import pandas as pd

from core import paths
from ml.train import evaluate

log = logging.getLogger(__name__)

# dbt's mart_settled_predictions does the grading join (earliest prediction
# per game, the no-contest 0-0 game left out), so this module and the
# dashboard's track record grade the same games. It is a view, so it sees
# the predictions ml.predict appended after dbt ran.
SETTLED_SQL = """
select game_id, model_version, game_date, predicted_margin, win_probability,
       margin, home_won
from main_marts.mart_settled_predictions
order by game_id
"""


def settled_predictions(con) -> pd.DataFrame:
    """Every graded prediction, by game."""
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

    # The mart may not exist yet (a warehouse dbt has not built) - that is
    # a normal state, not a failure, so a missing table degrades to
    # "nothing to score" instead of crashing the refresh.
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
