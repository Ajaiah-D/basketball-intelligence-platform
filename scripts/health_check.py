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
from datetime import UTC, date, datetime
from pathlib import Path

import duckdb

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
from core import paths
from core.constants import (
    LAST_RUN_MAX_AGE_DAYS,
    LATEST_GAME_MAX_AGE_DAYS,
    OFFSEASON_AFTER,
    OFFSEASON_BEFORE,
    WAREHOUSE_MAX_AGE_DAYS,
)

DB_PATH = paths.warehouse_path()
LOG_PATH = paths.logs_dir() / "refresh_runs.jsonl"

CHECKS_PASSED: list[str] = []
CHECKS_FAILED: list[str] = []


def ok(msg: str) -> None:
    CHECKS_PASSED.append(msg)
    print(f"  OK   {msg}")


def in_offseason(today: date | None = None) -> bool:
    """Roughly mid-April to mid-October (OFFSEASON_AFTER to OFFSEASON_BEFORE),
    when no regular season games are played. Stale data and an idle refresh
    job are the correct state then, not a problem, and a check that cries
    wolf all summer is a check nobody reads by the time the season starts."""
    today = today or date.today()
    return OFFSEASON_AFTER < (today.month, today.day) < OFFSEASON_BEFORE


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
    if age.days > WAREHOUSE_MAX_AGE_DAYS:
        fail(
            f"warehouse file is {age.days} days old "
            f"(last built more than {WAREHOUSE_MAX_AGE_DAYS} days ago)"
        )
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
            row = con.execute(f"select count(*) from {table}").fetchone()
        except duckdb.Error as exc:
            fail(f"{table}: query failed ({exc})")
            continue
        assert row is not None  # count(*) always returns one row
        n = row[0]
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
        row = con.execute("select max(game_date) from main_staging.stg_team_game_logs").fetchone()
    except duckdb.Error as exc:
        fail(f"could not read latest game date ({exc})")
        con.close()
        return
    con.close()
    assert row is not None  # an aggregate without GROUP BY always returns one row
    latest = row[0]
    if latest is None:
        fail("no games in the warehouse")
        return
    days_old = (datetime.now().date() - latest).days
    # During the regular season new games land every 1-3 days; give it a
    # generous week (LATEST_GAME_MAX_AGE_DAYS) before flagging the pipeline
    # as stalled.
    if in_offseason():
        ok(f"most recent game is {latest} ({days_old} days ago), expected in the offseason")
    elif days_old > LATEST_GAME_MAX_AGE_DAYS:
        fail(f"most recent game in the warehouse is {latest} ({days_old} days ago)")
    else:
        ok(f"most recent game in the warehouse is {latest} ({days_old} days ago)")


def scheduled_runs(lines: list[str]) -> list[dict]:
    """The run lines of refresh_runs.jsonl, minus git_push lines and dry runs."""
    records = [json.loads(line) for line in lines if line.strip()]
    return [r for r in records if "steps" in r and not r.get("dry_run")]


def last_scheduled_run(lines: list[str]) -> tuple[dict | None, dict | None]:
    """(the last real run, its git_push line or None) from refresh_runs.jsonl.

    The refresh appends its git push result as a separate line after the
    run's own line, and a --no-publish dry run writes a line marked
    "dry_run"; neither is the run this check is about.
    """
    records = [json.loads(line) for line in lines if line.strip()]
    runs = scheduled_runs(lines)
    if not runs:
        return None, None
    last = runs[-1]
    push = next(
        (
            r
            for r in reversed(records)
            if r.get("step") == "git_push" and r.get("run_at") == last["run_at"]
        ),
        None,
    )
    return last, push


def check_last_run() -> None:
    print("\nWeekly refresh job (scripts/weekly_refresh.py via Task Scheduler)")
    if not LOG_PATH.exists():
        fail(f"{LOG_PATH} does not exist - the scheduled job has never run")
        return
    lines = [line for line in LOG_PATH.read_text().splitlines() if line.strip()]
    last, push = last_scheduled_run(lines)
    if last is None:
        fail(f"{LOG_PATH} has no scheduled run in it")
        return
    run_at = datetime.fromisoformat(last["run_at"])
    age_days = (datetime.now(UTC) - run_at).days
    if not last.get("ok"):
        failed_step = next((s["step"] for s in last["steps"] if not s["ok"]), "unknown")
        fail(f"last run ({last['run_at']}, {age_days}d ago) FAILED at step '{failed_step}'")
    elif in_offseason():
        ok(
            f"last run {last['run_at']} ({age_days}d ago) succeeded; the weekly job "
            "is idle until the season starts"
        )
    elif age_days > LAST_RUN_MAX_AGE_DAYS:
        fail(
            f"last successful run was {last['run_at']} ({age_days}d ago) - "
            "the scheduled job may have stopped running"
        )
    else:
        ok(f"last run {last['run_at']} ({age_days}d ago) succeeded, {len(last['steps'])} steps")
    # A run can be "ok" overall and still have a failed step in it: the
    # payroll scrape and the player_impact refit are non-fatal by design
    # (see weekly_refresh.main), so their failures no longer show up in
    # last["ok"]. Report them anyway - non-fatal is not the same as
    # invisible - without failing the check, which would defeat the point
    # of making them non-fatal. Both keep last week's tables on failure.
    if last.get("ok"):
        for step in last["steps"]:
            if not step["ok"]:
                print(
                    f"  NOTE step '{step['step']}' failed but did not block the "
                    f"run; the warehouse is carrying last week's data for it"
                )
    # A dbt test configured to warn (assert_player_season_matches_game_logs
    # below its error threshold) passes the build, so the run is "ok" and
    # the warning would otherwise sit unread in that run's dbt_build.log.
    warnings = last.get("dbt_warnings") or 0
    if warnings:
        tests = ", ".join(last.get("dbt_warning_tests") or []) or "see dbt_build.log"
        print(f"  NOTE dbt finished that run with {warnings} warning(s): {tests}")
    # The release is already published by the time the run log is pushed,
    # so a failed push is not a failed refresh - but it does mean GitHub's
    # copy of this log is behind until the next run pushes it.
    if push is not None and not push.get("ok"):
        print(f"  NOTE git push after that run failed: {push.get('error', '')[-200:]}")
    runs = len(scheduled_runs(lines))
    print(f"  ({runs} scheduled run(s) recorded in {LOG_PATH.relative_to(PROJECT_ROOT)})")


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
    parser.add_argument("--skip-api", action="store_true", help="Skip the live nba_api smoke test")
    args = parser.parse_args()

    print(f"Health check @ {datetime.now(UTC).isoformat(timespec='seconds')}")
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
