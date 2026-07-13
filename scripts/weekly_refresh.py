"""Weekly data refresh: ingest -> DuckDB -> dbt -> release publish -> commit.

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
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOG_PATH = PROJECT_ROOT / "logs" / "refresh_runs.jsonl"
RELEASE_TAG = "data-v1"  # reused indefinitely so WAREHOUSE_URL never changes
PYTHON = sys.executable


def run_step(name: str, cmd: list[str], cwd: Path | None = None) -> dict:
    print(f"-> {name}")
    started = datetime.now(timezone.utc)
    result = subprocess.run(cmd, cwd=cwd or PROJECT_ROOT, capture_output=True, text=True)
    ok = result.returncode == 0
    entry = {
        "step": name,
        "ok": ok,
        "seconds": round((datetime.now(timezone.utc) - started).total_seconds(), 1),
    }
    if not ok:
        entry["error"] = (result.stderr or result.stdout)[-2000:]
    print(f"   {'OK' if ok else 'FAIL'} ({entry['seconds']}s)")
    return entry


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=PROJECT_ROOT, capture_output=True, text=True)


def main() -> None:
    dbt_dir = PROJECT_ROOT / "dbt" / "basketball_intelligence"
    run = {"run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "steps": []}

    steps = [
        ("ingest", [PYTHON, "ingestion/nba_ingest.py", "--force", "--pbp-games", "20"], None),
        ("load_duckdb", [PYTHON, "scripts/load_to_duckdb.py"], None),
        ("dbt_run", ["dbt", "run", "--profiles-dir", "."], dbt_dir),
        ("dbt_test", ["dbt", "test", "--profiles-dir", "."], dbt_dir),
        ("write_metadata", [PYTHON, "scripts/write_metadata.py"], None),
    ]

    run["ok"] = True
    for name, cmd, cwd in steps:
        entry = run_step(name, cmd, cwd)
        run["steps"].append(entry)
        if not entry["ok"]:
            run["ok"] = False
            break

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
        git("commit", "-m", f"Weekly refresh: {status} {run['run_at']}")
        git("push")

    sys.exit(0 if run["ok"] else 1)


if __name__ == "__main__":
    main()
