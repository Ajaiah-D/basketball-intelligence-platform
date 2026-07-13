"""Write data/last_updated.json from the current warehouse.

A small, git-committed status file so a refresh's outcome (timestamp, row
counts, season/date range) can be checked by reading one file on GitHub,
no need to download the 40+ MB warehouse just to ask "is this fresh."

Usage:
    python scripts/write_metadata.py
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "warehouse" / "basketball.duckdb"
OUT_PATH = PROJECT_ROOT / "data" / "last_updated.json"


def main() -> None:
    con = duckdb.connect(str(DB_PATH), read_only=True)
    player_rows, team_rows = (
        con.execute("select count(*) from raw.player_game_logs").fetchone()[0],
        con.execute("select count(*) from raw.team_game_logs").fetchone()[0],
    )
    first_season, last_season = con.execute(
        "select min(season), max(season) from main_staging.stg_team_game_logs"
    ).fetchone()
    latest_game_date = con.execute(
        "select max(game_date) from main_staging.stg_team_game_logs"
    ).fetchone()[0]
    con.close()

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps({
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "season_range": f"{first_season} to {last_season}",
        "latest_game_date": str(latest_game_date),
        "player_game_rows": player_rows,
        "team_game_rows": team_rows,
    }, indent=2) + "\n")
    print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
