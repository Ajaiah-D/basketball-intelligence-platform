"""Load raw parquet files from data/raw/ into the local DuckDB warehouse.

Creates warehouse/basketball.duckdb with a `raw` schema, one table per
parquet file. Tables are fully replaced on each run (raw layer is a
mirror of the latest ingestion; history/modeling belongs to dbt).

Usage:
    python scripts/load_to_duckdb.py
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import duckdb

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw"
DB_PATH = PROJECT_ROOT / "warehouse" / "basketball.duckdb"

log = logging.getLogger("load_to_duckdb")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S", stream=sys.stdout)

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
    con.execute("CREATE SCHEMA IF NOT EXISTS raw")

    for name, source in sources.items():
        table = f"raw.{name}"
        # union_by_name: older seasons can differ in column order/presence
        con.execute(
            f"CREATE OR REPLACE TABLE {table} AS "
            f"SELECT * FROM read_parquet(?, union_by_name=true)",
            [source],
        )
        rows = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        log.info("Loaded %-28s %8d rows", table, rows)

    con.close()
    log.info("Warehouse ready at %s", DB_PATH)


if __name__ == "__main__":
    main()
