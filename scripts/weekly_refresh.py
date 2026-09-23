"""Weekly data refresh: ingest -> DuckDB -> payroll -> dbt -> release publish -> commit.

ingest and load_duckdb are fatal - everything after them is built on what
they produce. The payroll scrape is not: it hits a third-party site, and a
week-old payroll parquet is a much smaller problem than the skipped
predictions and unpublished warehouse that blocking on it used to cause.
See main().

Meant to be run by a local Windows Task Scheduler job. stats.nba.com blocks
traffic from cloud/datacenter IP ranges (AWS, Azure, GCP, and GitHub Actions
runners all fall in that bucket), so this can't run as a normal GitHub
Actions job - it has to execute from a real residential IP, i.e. this
machine. See DEPLOYMENT.md.

Every run appends one line to logs/refresh_runs.jsonl (step-by-step
ok/fail, timing, error tail on failure) and commits it back to the repo
along with data/last_updated.json, so run history is checkable by reading
the repo, no always-on scheduler service or GitHub Actions log needed.

Usage:
    python scripts/weekly_refresh.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOG_PATH = PROJECT_ROOT / "logs" / "refresh_runs.jsonl"
RELEASE_TAG = "data-v1"  # reused indefinitely so WAREHOUSE_URL never changes
PYTHON = sys.executable
# Task Scheduler launches this with the venv's python.exe directly (not an
# activated shell), so the venv's Scripts/ dir isn't on child processes'
# PATH - resolve dbt's full path the same way sys.executable resolves python.
DBT = str(Path(PYTHON).parent / ("dbt.exe" if os.name == "nt" else "dbt"))

sys.path.insert(0, str(PROJECT_ROOT))
from scripts.season_teams import current_season_and_teams  # noqa: E402


def run_step(name: str, cmd: list[str], cwd: Path | None = None) -> dict:
    print(f"-> {name}")
    started = datetime.now(timezone.utc)
    try:
        result = subprocess.run(cmd, cwd=cwd or PROJECT_ROOT, capture_output=True, text=True)
        ok = result.returncode == 0
        error = None if ok else (result.stderr or result.stdout)[-2000:]
    except OSError as exc:
        # e.g. the executable itself couldn't be found/launched - still a
        # real failure worth logging, not a reason to crash silently.
        ok = False
        error = f"could not launch {cmd[0]!r}: {exc}"
    entry = {
        "step": name,
        "ok": ok,
        "seconds": round((datetime.now(timezone.utc) - started).total_seconds(), 1),
    }
    if not ok:
        entry["error"] = error
    print(f"   {'OK' if ok else 'FAIL'} ({entry['seconds']}s)")
    return entry


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=PROJECT_ROOT, capture_output=True, text=True)


def run_steps(run: dict, steps: list[tuple]) -> bool:
    """Run steps in order, recording each one; stop at the first failure."""
    for name, cmd, cwd in steps:
        entry = run_step(name, cmd, cwd)
        run["steps"].append(entry)
        if not entry["ok"]:
            return False
    return True


def payroll_steps() -> list[tuple]:
    """The payroll fetch, plus the reload that lands its output in the warehouse.

    Built at call time, not as a module-level constant, because the season and
    team list come from raw.team_game_logs - which only reflects this run's
    ingestion once "load_duckdb" has run. Computed any earlier, the first
    refresh after a season rollover would derive the *previous* season's teams,
    re-fetch ~30 already-static pages and skip the new season's payroll
    entirely until the following week. Deferring it also means importing this
    module no longer touches the database, so a fresh checkout with no
    warehouse yet can still bootstrap itself from nothing.
    """
    season, teams = current_season_and_teams()
    return [
        ("payroll", [PYTHON, "ingestion/team_payroll_ingest.py", "--force",
                     "--season", season, "--teams", *teams], None),
        # load_to_duckdb again: the payroll parquet was written after the first
        # load, and dbt runs next - without this it would query a warehouse a
        # week behind the file on disk.
        ("load_payroll", [PYTHON, "scripts/load_to_duckdb.py"], None),
    ]


def main() -> None:
    dbt_dir = PROJECT_ROOT / "dbt" / "basketball_intelligence"
    run = {"run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "steps": []}

    ok = run_steps(run, [
        ("ingest", [PYTHON, "ingestion/nba_ingest.py", "--force", "--pbp-games", "20"], None),
        ("load_duckdb", [PYTHON, "scripts/load_to_duckdb.py"], None),
    ])

    # Payroll is deliberately NON-FATAL. It is the one step that scrapes a
    # third party (Basketball-Reference), so it is also the one most likely
    # to fail for reasons that have nothing to do with this pipeline - a
    # rate limit, a page layout change, a bad gateway. Nothing downstream
    # reads this week's payroll file: the warehouse still has last week's,
    # which for a table that changes a few times a season is fine. Letting
    # that failure block dbt, the model and the release publish traded a
    # stale payroll number for no new predictions and an unpublished
    # warehouse - strictly the worse outage. ingest/load_duckdb above stay
    # fatal, because those failing means the actual game data is wrong or
    # missing and everything after them would be built on it.
    payroll_ok: bool | None = None  # None = never attempted (an earlier step failed)
    if ok:
        try:
            steps = payroll_steps()
        except Exception as exc:  # noqa: BLE001 - record it rather than crash the run
            run["steps"].append({"step": "payroll", "ok": False, "seconds": 0.0,
                                 "error": f"could not derive the current season/teams: {exc}"})
            payroll_ok = False
        else:
            payroll_ok = run_steps(run, steps)

    if ok:
        ok = run_steps(run, [
            ("dbt_seed", [DBT, "seed", "--profiles-dir", "."], dbt_dir),
            ("dbt_run", [DBT, "run", "--profiles-dir", "."], dbt_dir),
            ("dbt_test", [DBT, "test", "--profiles-dir", "."], dbt_dir),
            ("predict", [PYTHON, "-m", "ml.predict"], None),
            ("score_predictions", [PYTHON, "-m", "ml.evaluate"], None),
            ("write_metadata", [PYTHON, "scripts/write_metadata.py"], None),
        ])

    # Not folded into run["ok"]: that flag gates the release publish below
    # and the job's exit code, and a failed payroll fetch must stop neither.
    # It is recorded separately (and in run["steps"]) so health_check.py can
    # still surface it and it is not silently swallowed.
    run["payroll_ok"] = payroll_ok
    run["ok"] = ok
    if run["ok"]:
        version_path = PROJECT_ROOT / "warehouse" / "version.txt"
        version_path.write_text(datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        entry = run_step(
            "publish_release",
            ["gh", "release", "upload", RELEASE_TAG,
             "warehouse/basketball.duckdb", "warehouse/version.txt", "--clobber"],
        )
        run["steps"].append(entry)
        run["ok"] = entry["ok"]

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(run) + "\n")

    git("add", "data/last_updated.json", "logs/refresh_runs.jsonl")
    if git("diff", "--cached", "--quiet").returncode != 0:
        status = "ok" if run["ok"] else "FAILED"
        if run["ok"] and payroll_ok is False:
            status = "ok (payroll step failed)"
        git("commit", "-m", f"Weekly refresh: {status} {run['run_at']}")
        git("push")

    sys.exit(0 if run["ok"] else 1)


if __name__ == "__main__":
    main()
