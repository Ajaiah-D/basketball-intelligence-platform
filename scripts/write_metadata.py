"""Write data/last_updated.json from the current warehouse.

A small, git-committed status file so a refresh's outcome (timestamp, row
counts, season/date range) can be checked by reading one file on GitHub,
no need to download the 40+ MB warehouse just to ask "is this fresh."

Usage:
    python scripts/write_metadata.py
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import duckdb

# Run as `python scripts/write_metadata.py`, so the repo root is not on the path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import paths

DB_PATH = paths.warehouse_path()
OUT_PATH = paths.last_updated_path()


def _one_row(con: duckdb.DuckDBPyConnection, sql: str) -> tuple:
    """The single row of an aggregate query (no GROUP BY, so always one)."""
    row = con.execute(sql).fetchone()
    assert row is not None
    return row


def main() -> None:
    con = duckdb.connect(str(DB_PATH), read_only=True)
    player_rows, team_rows = (
        _one_row(con, "select count(*) from raw.player_game_logs")[0],
        _one_row(con, "select count(*) from raw.team_game_logs")[0],
    )
    first_season, last_season = _one_row(
        con, "select min(season), max(season) from main_staging.stg_team_game_logs"
    )
    (latest_game_date,) = _one_row(
        con, "select max(game_date) from main_staging.stg_team_game_logs"
    )
    con.close()

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        json.dumps(
            {
                "updated_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "season_range": f"{first_season} to {last_season}",
                "latest_game_date": str(latest_game_date),
                "player_game_rows": player_rows,
                "team_game_rows": team_rows,
            },
            indent=2,
        )
        + "\n"
    )
    print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
