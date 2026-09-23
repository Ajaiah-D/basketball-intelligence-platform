"""Which team codes were active in which season, read from the warehouse.

The payroll backfill (scripts/backfill_team_payroll.py) and the weekly refresh
(scripts/weekly_refresh.py) both need this, and neither should hand-maintain a
relocation/expansion table: raw.team_game_logs already carries the full
historical franchise-code history from nba_api ingestion.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "warehouse" / "basketball.duckdb"
FIRST_PAYROLL_SEASON = "1984-85"  # payroll has no meaning before the salary cap existed


def seasons_and_teams(first_season: str = FIRST_PAYROLL_SEASON) -> dict[str, list[str]]:
    """{season: [team codes active that season]}, first_season onward, oldest first."""
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        # The "as team_abbreviation" alias looks redundant but is not: the
        # underlying nba_api column is TEAM_ABBREVIATION (uppercase). DuckDB
        # matches it case-insensitively but names the result column after the
        # stored casing, and the pandas lookup below is case-sensitive, so
        # without the alias .df() yields "TEAM_ABBREVIATION" and this KeyErrors.
        df = con.execute(
            "select distinct season, team_abbreviation as team_abbreviation "
            "from raw.team_game_logs where season >= ? order by season",
            [first_season],
        ).df()
    finally:
        con.close()
    return {
        season: sorted(group["team_abbreviation"].tolist())
        for season, group in df.groupby("season")
    }


def current_season_and_teams() -> tuple[str, list[str]]:
    """(most recent season in the warehouse, team codes active that season)."""
    by_season = seasons_and_teams()
    if not by_season:
        raise RuntimeError(f"no seasons in raw.team_game_logs at {DB_PATH}")
    season = max(by_season)
    return season, by_season[season]
