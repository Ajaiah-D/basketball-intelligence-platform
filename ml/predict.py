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

    from ml.elo import BASE_RATING, current_ratings
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
            # can be carried forward honestly: ml.elo.current_ratings()
            # gives each team's actual current rating (post-last-game, and
            # correctly regressed toward the mean if the target season
            # hasn't started yet - e.g. opening night, when compute_elo's
            # own season-transition regression never fires because it only
            # runs while processing a row FROM the new season). Every other
            # feature is zero-filled, consistent with walk_forward's own
            # fillna(0.0) tolerance for missing values. Flagged in the
            # task-10 report as the one place this module's predictions
            # should be revisited once a real forward feature pipeline
            # exists for the rest of FEATURE_COLUMNS.
            games = con.execute(
                """
                select game_id, season, game_date, home_team_id, away_team_id,
                       home_won, is_neutral_site
                from main_marts.fct_team_game
                where not (home_points = 0 and away_points = 0)
                order by game_date, game_id
                """
            ).df()
            # Seasons don't overlap and there is a months-long gap between
            # them, so the 7-day slate window always falls inside exactly
            # one season in practice - this is not expected to ever fire,
            # but if the schedule ever did span two seasons in one window,
            # taking the first would silently rate the second season's
            # games against the wrong target season's regression.
            target_seasons = slate["season"].unique()
            if len(target_seasons) != 1:
                raise ValueError(
                    f"expected one season in the slate window, got {target_seasons!r}"
                )
            target_season = target_seasons[0]
            latest_elo = current_ratings(games, target_season)

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
