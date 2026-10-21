"""Load raw parquet files from data/raw/ into the local DuckDB warehouse.

Creates warehouse/basketball.duckdb with a `raw` schema, one table per
parquet file. Tables are fully replaced on each run (raw layer is a
mirror of the latest ingestion; history/modeling belongs to dbt).

It also rebuilds main.predictions from the committed
data/predictions/history.csv, the one record that is not re-derived from
the API each week. Without that file an existing predictions table is left
as it is.

Usage:
    python scripts/load_to_duckdb.py
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import duckdb

# Run as `python scripts/load_to_duckdb.py`, so the repo root is not on the path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import paths
from ml.predict import load_history

RAW_DIR = paths.raw_dir()
DB_PATH = paths.warehouse_path()
PREDICTIONS_CSV = paths.predictions_history_path()

log = logging.getLogger("load_to_duckdb")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )

    # Single-file tables plus per-season directories (one parquet per season).
    sources: dict[str, str] = {}
    for path in sorted(RAW_DIR.glob("*.parquet")):
        sources[path.stem] = str(path)
    for directory in sorted(d for d in RAW_DIR.iterdir() if d.is_dir()):
        if any(directory.glob("*.parquet")):
            sources[directory.name] = str(directory / "*.parquet")
    if not sources:
        raise SystemExit(f"No parquet files in {RAW_DIR}. Run ingestion/nba_ingest.py first.")

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB_PATH))
    try:
        # One transaction for every table: a parquet that fails to load
        # leaves the whole raw layer as the previous load left it, instead of
        # half this week's tables next to half last week's.
        con.execute("BEGIN TRANSACTION")
        try:
            con.execute("CREATE SCHEMA IF NOT EXISTS raw")
            for name, source in sources.items():
                table = f"raw.{name}"
                # union_by_name: older seasons can differ in column order/presence
                con.execute(
                    f"CREATE OR REPLACE TABLE {table} AS "
                    "SELECT * FROM read_parquet(?, union_by_name=true)",
                    [source],
                )
                row = con.execute(f"SELECT count(*) FROM {table}").fetchone()
                assert row is not None  # count(*) always returns one row
                log.info("Loaded %-28s %8d rows", table, row[0])
            # In the same transaction: a bad history rolls back the raw
            # layer with it, rather than publishing new games beside an
            # empty track record.
            if PREDICTIONS_CSV.is_file():
                rows = load_history(con, PREDICTIONS_CSV)
                log.info("Loaded %-28s %8d rows", "main.predictions", rows)
            con.execute("COMMIT")
        except BaseException:
            con.execute("ROLLBACK")
            raise
    finally:
        con.close()
    log.info("Warehouse ready at %s", DB_PATH)


if __name__ == "__main__":
    main()
