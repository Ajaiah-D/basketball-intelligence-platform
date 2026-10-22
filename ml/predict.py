"""Predict the upcoming slate and append the results.

The predictions table is append-only on purpose. A public track record is
only worth anything if the predictions in it cannot be revised after the
games are played, so a re-run inserts new rows rather than replacing old
ones, and every row carries the model version that produced it.

The warehouse is rebuilt every week, so the table alone could not keep that
promise: data/predictions/history.csv, committed with every refresh, is the
source of truth. Each run appends its predictions to the CSV and to the
table; scripts/load_to_duckdb.py rebuilds the table from the CSV. A game is
predicted again by every run until it is played - ml.evaluate grades the
earliest prediction, the page shows the latest - so a game has one row per
run, and (game_id, model_version, predicted_at) is the key.
"""

from __future__ import annotations

import csv
import io
import logging
import os
import sys
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pandas as pd

from core import paths
from core.io import atomic_write_bytes

MODEL_VERSION = "ridge-v1"

# The table's columns, in order, with their DuckDB types. The CSV has
# exactly these columns in this order, and the loader reads it with exactly
# these types, so a rebuilt table matches one ml.predict created.
PREDICTION_COLUMNS: dict[str, str] = {
    "prediction_id": "varchar",
    "model_version": "varchar",
    "predicted_at": "timestamp",
    "game_id": "varchar",
    "season": "varchar",
    "game_date": "date",
    "home_team_id": "bigint",
    "away_team_id": "bigint",
    "predicted_margin": "double",
    "win_probability": "double",
}

CREATE_TABLE = (
    "create table if not exists predictions (\n"
    + ",\n".join(f"    {name:<16} {kind}" for name, kind in PREDICTION_COLUMNS.items())
    + "\n)"
)

# One row per game per run: a run stamps every row with the same
# predicted_at, and later runs predict the same game again on purpose.
HISTORY_KEY = ("game_id", "model_version", "predicted_at")

# Set to 1 by `weekly_refresh.py --no-publish`: a dry run still writes the
# warehouse copy's table, but must not add rows to the committed history
# that the next real run would then commit as if they had been published.
DRY_RUN_ENV = "BIP_DRY_RUN"

# Production forecasting window: the slate the model can plausibly speak to
# right now, not the whole rest of the season.
THROUGH_DAYS_AHEAD = 7

# Fixed width with microseconds always present, so the strings sort in time
# order and the same instant is always written the same way.
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S.%f"

log = logging.getLogger(__name__)

# The subset of ml.features.FEATURE_COLUMNS that can actually be computed
# for a game that has not been played yet. A scheduled game has no
# mart_game_features row, so the rolling-form and rest features do not
# exist for it; Elo is the one signal that carries forward honestly. The
# production fit below uses exactly this list, so the model is fit on the
# same columns it is served - see the comment in fit_and_predict for why
# fitting on all 18 and zeroing 14 at serve time was worse.
#
# is_neutral_site is deliberately NOT here, even though upcoming_slate()
# selects it. Do not re-add it without reading this: the flag means two
# different things in the two places it comes from. fct_team_game's
# is_neutral_site is a heuristic - true only when the source marks BOTH
# teams away in the matchup string - which fires on 10 of 52,848
# historical games and is known to miss the 2020 Orlando bubble and most
# international games. stg_schedule's is_neutral_site is the schedule
# feed's own explicit isNeutral field, a different signal, true for 3 of
# the 1,206 games in the 2026-27 schedule. Training a coefficient on the
# first definition (10 positive examples - essentially noise; it fits to
# roughly -3 points) and applying it to the second is incoherent, and
# would hand a fabricated three-point adjustment to whichever future
# games the feed happens to flag. Reconciling the two definitions across
# the two dbt models is real work and has not been done; until it is, the
# model neither fits nor serves this column. Backtest confirms dropping
# it costs nothing (Brier identical to four decimal places).
SERVED_COLUMNS = ["home_elo_pre", "away_elo_pre", "elo_diff"]


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


def stamp_predictions(rows: pd.DataFrame, now: datetime | None = None) -> pd.DataFrame:
    """Give model output its id, model version and time, in table column order.

    `now` is for tests; a real run stamps the current UTC time (naive, as
    the table stores it).
    """
    stamped = rows.copy()
    stamped["prediction_id"] = [str(uuid.uuid4()) for _ in range(len(stamped))]
    stamped["model_version"] = MODEL_VERSION
    stamped["predicted_at"] = now or datetime.now(UTC).replace(tzinfo=None)
    return stamped[list(PREDICTION_COLUMNS)].reset_index(drop=True)


def write_predictions(con, predictions: pd.DataFrame) -> int:
    """Append stamped predictions to the warehouse table. Returns the number
    of rows written."""
    if predictions.empty:
        return 0
    con.execute(CREATE_TABLE)
    columns = ", ".join(PREDICTION_COLUMNS)
    con.register("_incoming", predictions[list(PREDICTION_COLUMNS)])
    try:
        con.execute(f"insert into predictions ({columns}) select {columns} from _incoming")
    finally:
        con.unregister("_incoming")
    return len(predictions)


# -- the committed history ------------------------------------------------------


def _format(value: object, kind: str) -> str:
    # Each value always becomes the same text, so writing a row read back
    # from the CSV reproduces its bytes. Floats use the shortest repr that
    # round-trips: no precision lost, no %.6f rounding of the public record.
    if value is None or pd.isna(value):  # type: ignore[call-overload]
        return ""
    if kind == "timestamp":
        stamp = pd.Timestamp(value)  # type: ignore[arg-type]
        # The table stores naive UTC; an aware value must not be written in
        # its own zone and then read back as if it were UTC.
        if stamp.tzinfo is not None:
            stamp = stamp.tz_convert("UTC").tz_localize(None)
        return stamp.strftime(TIMESTAMP_FORMAT)
    if kind == "date":
        return pd.Timestamp(value).strftime("%Y-%m-%d")  # type: ignore[arg-type]
    if kind == "bigint":
        return str(int(value))  # type: ignore[call-overload]
    if kind == "double":
        return repr(float(value))  # type: ignore[arg-type]
    return str(value)


def _check_header(header: list[str], path: Path) -> None:
    if header != list(PREDICTION_COLUMNS):
        raise ValueError(
            f"{path} has header {header}, expected {list(PREDICTION_COLUMNS)}; "
            "the history is never rewritten, so fix it by hand"
        )


def append_history(predictions: pd.DataFrame, path: Path) -> int:
    """Append stamped predictions to the history CSV. Returns rows added.

    Rows already in the file (same game, model version and predicted_at - a
    retried run) are skipped. The batch is sorted by predicted_at then
    game_id; a batch that would sort before the file's last row is refused,
    because the only way to keep that order would be to reorder past rows.
    Past rows' bytes are copied as they are, in the file's own line ending,
    and the whole file is swapped in atomically: a crash leaves the old
    history, never a half-written row.
    """
    if predictions.empty:
        return 0
    kinds = list(PREDICTION_COLUMNS.values())
    batch = [
        [_format(v, kind) for v, kind in zip(row, kinds, strict=True)]
        for row in predictions[list(PREDICTION_COLUMNS)].itertuples(index=False)
    ]
    names = list(PREDICTION_COLUMNS)
    key_at = [names.index(k) for k in HISTORY_KEY]
    order_at = (names.index("predicted_at"), names.index("game_id"))

    def key(row: list[str]) -> tuple[str, ...]:
        return tuple(row[i] for i in key_at)

    def order(row: list[str]) -> tuple[str, ...]:
        return tuple(row[i] for i in order_at)

    if len({key(r) for r in batch}) != len(batch):
        raise ValueError("the batch holds a duplicate (game_id, model_version, predicted_at)")
    batch.sort(key=order)

    existing = path.read_bytes() if path.exists() else b""
    newline = "\n"
    seen: set[tuple[str, ...]] = set()
    last: tuple[str, ...] | None = None
    if existing:
        text = existing.decode("utf-8")
        if not text.endswith("\n"):
            raise ValueError(f"{path} does not end with a newline")
        if text.split("\n", 1)[0].endswith("\r"):
            newline = "\r\n"
        rows = list(csv.reader(io.StringIO(text, newline="")))
        _check_header(rows[0], path)
        seen = {key(r) for r in rows[1:]}
        last = max((order(r) for r in rows[1:]), default=None)

    new = [r for r in batch if key(r) not in seen]
    if not new:
        return 0
    if last is not None and order(new[0]) < last:
        raise ValueError(
            f"predictions stamped {new[0][order_at[0]]} are older than the newest "
            f"row in {path} ({last[0]}); appending them would break its order. "
            "Check the system clock (predicted_at is UTC now), or if that last "
            "row's time is wrong, fix it by hand and commit the fix"
        )

    out = io.StringIO()
    writer = csv.writer(out, lineterminator=newline)
    if not existing:
        writer.writerow(names)
    writer.writerows(new)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(existing + out.getvalue().encode("utf-8"), path)
    return len(new)


def read_history_sql() -> str:
    """A select over the history CSV (the one ? parameter is its path) that
    yields the table's columns with the table's types."""
    columns = ", ".join(f"'{name}': '{kind.upper()}'" for name, kind in PREDICTION_COLUMNS.items())
    return (
        "select * from read_csv(?, header = true, auto_detect = false, "
        f"delim = ',', quote = '\"', columns = {{{columns}}})"
    )


def load_history(con, path: Path) -> int:
    """Replace main.predictions with the history CSV's rows. Returns the row
    count. Runs inside the caller's transaction, if it has one."""
    with path.open(encoding="utf-8", newline="") as f:
        _check_header(next(csv.reader(f), []), path)
    con.execute(f"create or replace table main.predictions as {read_history_sql()}", [str(path)])
    row = con.execute("select count(*) from main.predictions").fetchone()
    return int(row[0]) if row else 0


# -- the run --------------------------------------------------------------------


def fit_and_predict(con, through: date | None = None) -> pd.DataFrame:
    """Fit on every played game and predict the slate through `through`
    (default: THROUGH_DAYS_AHEAD from today). Returns stamped rows in table
    column order; empty when nothing is scheduled."""
    from ml.elo import BASE_RATING, current_ratings
    from ml.features import build_feature_frame, load_played_games
    from ml.train import margin_to_win_probability

    if through is None:
        through = date.today() + timedelta(days=THROUGH_DAYS_AHEAD)
    slate = upcoming_slate(con, through)
    if slate.empty:
        return pd.DataFrame(columns=list(PREDICTION_COLUMNS))

    # Fit on every played game in the warehouse. This is a production fit,
    # not a backtest - ml/train.py's walk_forward is what proves the
    # methodology out of sample; this just needs the best model trainable on
    # everything known as of right now.
    #
    # Scheduled games have no mart_game_features row of their own (that mart
    # is built from games that have already been played), so most
    # pre-tipoff features - rolling form, rest days - cannot be computed for
    # them yet without a forward-looking feature pipeline this task does not
    # build. Elo is the one feature that can be carried forward honestly:
    # ml.elo.current_ratings() gives each team's actual current rating
    # (post-last-game, and correctly regressed toward the mean if the target
    # season hasn't started yet - e.g. opening night, when compute_elo's own
    # season-transition regression never fires because it only runs while
    # processing a row FROM the new season).
    #
    # So the fit uses SERVED_COLUMNS, not all of FEATURE_COLUMNS. This module
    # used to fit on all 18 columns and then hard-zero the 14 it cannot
    # compute at serve time. That is not merely information loss: the fitted
    # coefficients assume all 18 carry real signal, so zeroing most of them
    # feeds the model a systematically miscalibrated input. Fitting on the
    # same reduced set that is actually served is better calibrated on every
    # metric. Walk-forward from 2005-06 over 25,268 games, Ridge(alpha=1.0):
    # fit-18-serve-4 gives Brier 0.2166, log loss 0.6229, margin MAE 10.13;
    # fitting and serving the reduced set gives Brier 0.2142, log loss
    # 0.6168, MAE 10.08. Still flagged in the task-10 report as the place to
    # revisit once a real forward feature pipeline exists - the fix then is
    # to widen SERVED_COLUMNS, which widens the fit with it.
    history = build_feature_frame(con)
    X_train = history[SERVED_COLUMNS].astype(float).fillna(0.0)
    from sklearn.linear_model import Ridge

    model = Ridge().fit(X_train, history["margin"].astype(float))

    games = load_played_games(con)
    # Seasons don't overlap and there is a months-long gap between them, so
    # the 7-day slate window always falls inside exactly one season in
    # practice - this is not expected to ever fire, but if the schedule ever
    # did span two seasons in one window, taking the first would silently
    # rate the second season's games against the wrong target season's
    # regression.
    target_seasons = slate["season"].unique()
    if len(target_seasons) != 1:
        raise ValueError(f"expected one season in the slate window, got {target_seasons!r}")
    target_season = target_seasons[0]
    latest_elo = current_ratings(games, target_season)

    rows = slate.copy()
    rows["home_elo_pre"] = rows["home_team_id"].map(latest_elo).fillna(BASE_RATING)
    rows["away_elo_pre"] = rows["away_team_id"].map(latest_elo).fillna(BASE_RATING)
    rows["elo_diff"] = rows["home_elo_pre"] - rows["away_elo_pre"]
    X_slate = rows[SERVED_COLUMNS].astype(float).fillna(0.0)

    rows["predicted_margin"] = model.predict(X_slate)
    rows["win_probability"] = margin_to_win_probability(rows["predicted_margin"])
    return stamp_predictions(rows)


def is_dry_run() -> bool:
    """Whether DRY_RUN_ENV asks this run to leave the history alone."""
    return os.environ.get(DRY_RUN_ENV, "") not in ("", "0")


def main() -> None:
    """Predict the coming week, append it to the history CSV (unless this is
    a dry run) and to the warehouse table."""
    import duckdb

    through = date.today() + timedelta(days=THROUGH_DAYS_AHEAD)
    con = duckdb.connect(str(paths.warehouse_path()))
    try:
        predictions = fit_and_predict(con, through)
        if predictions.empty:
            log.info("No games scheduled through %s; wrote 0 predictions.", through)
            return
        # The CSV first: if the table insert then fails, the next load
        # rebuilds the table from the CSV. The other way round, a published
        # prediction could be missing from the record it is graded from.
        history = paths.predictions_history_path()
        if is_dry_run():
            log.info("Dry run (%s set): not appending to %s", DRY_RUN_ENV, history)
        else:
            try:
                added = append_history(predictions, history)
            except ValueError as exc:
                # The last line of the step's output is what the refresh
                # records as the failure, so make it the reason, not a
                # traceback's tail.
                log.error("Not writing predictions: %s", exc)
                raise SystemExit(1) from exc
            log.info("Appended %d predictions to %s", added, history)
        written = write_predictions(con, predictions)
        log.info("Wrote %d predictions for games through %s.", written, through)
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
