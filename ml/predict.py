"""Predict the upcoming slate and append the results.

The predictions table is append-only on purpose. A public track record is
only worth anything if the predictions in it cannot be revised after the
games are played, so a re-run inserts new rows rather than replacing old
ones, and every row carries the model version that produced it.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

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


if __name__ == "__main__":
    from pathlib import Path

    import duckdb

    from ml.elo import BASE_RATING, compute_elo
    from ml.features import FEATURE_COLUMNS, build_feature_frame
    from ml.train import margin_to_win_probability

    # Production forecasting window: the slate the model can plausibly speak
    # to right now, not the whole rest of the season.
    THROUGH_DAYS_AHEAD = 7

    db_path = Path(__file__).resolve().parent.parent / "warehouse" / "basketball.duckdb"
    con = duckdb.connect(str(db_path))
    try:
        through = date.today() + timedelta(days=THROUGH_DAYS_AHEAD)
        slate = upcoming_slate(con, through)

        if slate.empty:
            print(f"No games scheduled through {through}; wrote 0 predictions.")
        else:
            # Fit on every played game in the warehouse. This is a
            # production fit, not a backtest - ml/train.py's walk_forward is
            # what proves the methodology out of sample; this just needs the
            # best model trainable on everything known as of right now.
            history = build_feature_frame(con)
            X_train = history[FEATURE_COLUMNS].astype(float).fillna(0.0)
            from sklearn.linear_model import Ridge

            model = Ridge().fit(X_train, history["margin"].astype(float))

            # Scheduled games have no mart_game_features row of their own
            # (that mart is built from games that have already been played),
            # so most pre-tipoff features - rolling form, rest days - cannot
            # be computed for them yet without a forward-looking feature
            # pipeline this task does not build. Elo is the one feature that
            # can be carried forward honestly: a team's rating entering its
            # most recent played game, taken from compute_elo's own
            # pre-game output, so nothing here looks at a result the model
            # would not have known about pre-tipoff. This is an
            # approximation (it is off by that one game's adjustment, at
            # most k=20 Elo points) rather than the team's literal
            # current rating, and every other feature is zero-filled,
            # consistent with walk_forward's own fillna(0.0) tolerance for
            # missing values. Flagged in the task-10 report as the one place
            # this module's predictions should be revisited once a real
            # forward feature pipeline exists.
            games = con.execute(
                """
                select game_id, season, game_date, home_team_id, away_team_id,
                       home_won, is_neutral_site
                from main_marts.fct_team_game
                where not (home_points = 0 and away_points = 0)
                order by game_date, game_id
                """
            ).df()
            elo = compute_elo(games).set_index("game_id")
            latest_elo: dict[int, float] = {}
            for g in games.sort_values(["game_date", "game_id"]).itertuples(index=False):
                pre = elo.loc[g.game_id]
                latest_elo[g.home_team_id] = pre["home_elo_pre"]
                latest_elo[g.away_team_id] = pre["away_elo_pre"]

            rows = slate.copy()
            rows["home_elo_pre"] = rows["home_team_id"].map(latest_elo).fillna(BASE_RATING)
            rows["away_elo_pre"] = rows["away_team_id"].map(latest_elo).fillna(BASE_RATING)
            rows["elo_diff"] = rows["home_elo_pre"] - rows["away_elo_pre"]
            for column in FEATURE_COLUMNS:
                if column not in rows.columns:
                    rows[column] = 0.0
            X_slate = rows[FEATURE_COLUMNS].astype(float).fillna(0.0)

            rows["predicted_margin"] = model.predict(X_slate)
            rows["win_probability"] = margin_to_win_probability(rows["predicted_margin"])

            written = write_predictions(con, rows)
            print(f"Wrote {written} predictions for games through {through}.")
    finally:
        con.close()
