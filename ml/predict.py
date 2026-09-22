"""Predict the upcoming slate and append the results.

The predictions table is append-only on purpose. A public track record is
only worth anything if the predictions in it cannot be revised after the
games are played, so a re-run inserts new rows rather than replacing old
ones, and every row carries the model version that produced it.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pandas as pd

MODEL_VERSION = "ridge-v1"

CREATE_TABLE = """
create table if not exists predictions (
    prediction_id    varchar,
    model_version    varchar,
    predicted_at     timestamp,
    game_id          varchar,
    season           varchar,
    game_date        date,
    home_team_id     bigint,
    away_team_id     bigint,
    predicted_margin double,
    win_probability  double
)
"""


def upcoming_slate(con, through: date) -> pd.DataFrame:
    """Scheduled, not-yet-played REGULAR SEASON games up to and including
    `through`. game_status = 1 alone would also include preseason -
    Task 8 found the schedule feed needs is_regular_season to separate
    them (gameStatus doesn't carry a game-type distinction)."""
    return con.execute(
        """
        select season, game_id, game_date, home_team_id, away_team_id,
               is_neutral_site
        from main_staging.stg_schedule
        where game_status = 1 and is_regular_season and game_date <= ?
        order by game_date, game_id
        """,
        [through],
    ).df()


def write_predictions(con, rows: pd.DataFrame) -> int:
    """Append predictions. Returns the number of rows written."""
    if rows.empty:
        return 0
    con.execute(CREATE_TABLE)
    stamped = rows.copy()
    stamped["prediction_id"] = [str(uuid.uuid4()) for _ in range(len(stamped))]
    stamped["model_version"] = MODEL_VERSION
    stamped["predicted_at"] = datetime.now(timezone.utc).replace(tzinfo=None)
    stamped = stamped[[
        "prediction_id", "model_version", "predicted_at", "game_id", "season",
        "game_date", "home_team_id", "away_team_id", "predicted_margin",
        "win_probability",
    ]]
    con.register("_incoming", stamped)
    con.execute("insert into predictions select * from _incoming")
    con.unregister("_incoming")
    return len(stamped)
