"""Sanity-check the pipeline and warehouse without re-running anything.

Meant to be run on demand (by you, or by an assistant you point at this
repo) to answer "is the data still good": is the warehouse recent, does
row-count look sane, does the NBA API still respond. Exits non-zero on
any failed check so it can also be scripted.

Usage:
    python scripts/health_check.py
    python scripts/health_check.py --skip-api    # skip the live API call
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import duckdb

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "warehouse" / "basketball.duckdb"
LOG_PATH = PROJECT_ROOT / "logs" / "refresh_runs.jsonl"

CHECKS_PASSED: list[str] = []
CHECKS_FAILED: list[str] = []


def ok(msg: str) -> None:
    CHECKS_PASSED.append(msg)
    print(f"  OK   {msg}")


def fail(msg: str) -> None:
    CHECKS_FAILED.append(msg)
    print(f"  FAIL {msg}")


def check_warehouse_file() -> None:
    print("\nWarehouse file")
    if not DB_PATH.exists():
        fail(f"{DB_PATH} does not exist")
        return
    size_mb = DB_PATH.stat().st_size / (1024 * 1024)
    ok(f"{DB_PATH.name} exists ({size_mb:.1f} MB)")
    age = datetime.now() - datetime.fromtimestamp(DB_PATH.stat().st_mtime)
    if age.days > 14:
        fail(f"warehouse file is {age.days} days old (last built more than 2 weeks ago)")
    else:
        ok(f"warehouse file is {age.days} day(s) old")


def check_row_counts() -> None:
    print("\nRow counts")
    if not DB_PATH.exists():
        fail("skipped: no warehouse file")
        return
    con = duckdb.connect(str(DB_PATH), read_only=True)
    tables = [
        ("raw.player_game_logs", 100_000),
        ("raw.team_game_logs", 10_000),
        ("main_staging.stg_player_game_logs", 100_000),
        ("main_staging.stg_team_game_logs", 10_000),
    ]
    for table, min_rows in tables:
        try:
            n = con.execute(f"select count(*) from {table}").fetchone()[0]
        except duckdb.Error as exc:
            fail(f"{table}: query failed ({exc})")
            continue
        if n < min_rows:
            fail(f"{table}: only {n:,} rows (expected >= {min_rows:,})")
        else:
            ok(f"{table}: {n:,} rows")
    con.close()


def check_freshness() -> None:
    print("\nData freshness")
    if not DB_PATH.exists():
        fail("skipped: no warehouse file")
        return
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        latest = con.execute(
            "select max(game_date) from main_staging.stg_team_game_logs"
        ).fetchone()[0]
    except duckdb.Error as exc:
        fail(f"could not read latest game date ({exc})")
        con.close()
        return
    con.close()
    if latest is None:
        fail("no games in the warehouse")
        return
    days_old = (datetime.now().date() - latest).days
    # During the regular season new games land every 1-3 days; give it a
    # generous week of slack before flagging the pipeline as stalled.
    if days_old > 7:
        fail(f"most recent game in the warehouse is {latest} ({days_old} days ago)")
    else:
        ok(f"most recent game in the warehouse is {latest} ({days_old} days ago)")


def check_last_run() -> None:
    print("\nWeekly refresh job (scripts/weekly_refresh.py via Task Scheduler)")
    if not LOG_PATH.exists():
        fail(f"{LOG_PATH} does not exist - the scheduled job has never run")
        return
    lines = [line for line in LOG_PATH.read_text().splitlines() if line.strip()]
    if not lines:
        fail(f"{LOG_PATH} is empty")
        return
    last = json.loads(lines[-1])
    run_at = datetime.fromisoformat(last["run_at"])
    age_days = (datetime.now(timezone.utc) - run_at).days
    if not last.get("ok"):
        failed_step = next((s["step"] for s in last["steps"] if not s["ok"]), "unknown")
        fail(f"last run ({last['run_at']}, {age_days}d ago) FAILED at step '{failed_step}'")
    elif age_days > 10:
        fail(f"last successful run was {last['run_at']} ({age_days}d ago) - "
             "the scheduled job may have stopped running")
    else:
        ok(f"last run {last['run_at']} ({age_days}d ago) succeeded, "
           f"{len(last['steps'])} steps")
    print(f"  ({len(lines)} run(s) recorded in {LOG_PATH.relative_to(PROJECT_ROOT)})")


def check_api(skip: bool) -> None:
    print("\nNBA API connectivity")
    if skip:
        print("  --skip-api passed, skipping")
        return
    try:
        sys.path.insert(0, str(PROJECT_ROOT))
        from nba_api.stats.endpoints import leaguegamelog

        from ingestion.nba_ingest import current_season
        df = leaguegamelog.LeagueGameLog(
            season=current_season(),
            player_or_team_abbreviation="T",
            season_type_all_star="Regular Season",
            timeout=30,
        ).get_data_frames()[0]
    except Exception as exc:
        fail(f"stats.nba.com did not respond as expected: {exc}")
        return
    if df.empty:
        fail("stats.nba.com returned zero rows for the current season")
    else:
        ok(f"stats.nba.com responded ({len(df)} rows for the current season)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--skip-api", action="store_true",
                        help="Skip the live nba_api smoke test")
    args = parser.parse_args()

    print(f"Health check @ {datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    check_warehouse_file()
    check_row_counts()
    check_freshness()
    check_last_run()
    check_api(args.skip_api)

    print(f"\n{len(CHECKS_PASSED)} passed, {len(CHECKS_FAILED)} failed")
    if CHECKS_FAILED:
        sys.exit(1)


if __name__ == "__main__":
    main()
