"""Weekly data refresh: ingest -> DuckDB -> payroll -> dbt -> player impact ->
predictions -> swap in -> release publish -> commit.

The warehouse is built in a copy (warehouse/next/basketball.duckdb, beside
the real file). Every step runs against the copy, and only when every required step
has passed is the copy swapped onto the real path and published. A failed
run deletes the copy and leaves the real warehouse - and the published
release - exactly as last week's run left them.

ingest, load_duckdb and dbt_build are fatal - everything after them is
built on what they produce. The payroll scrape and the Arcade's
player-impact refit are not: a week-old payroll parquet or a week-old impact
table is a much smaller problem than the skipped predictions and unpublished
warehouse that blocking on them would cause. See build().

Meant to be run by a local Windows Task Scheduler job. stats.nba.com blocks
traffic from cloud/datacenter IP ranges (AWS, Azure, GCP, and GitHub Actions
runners all fall in that bucket), so this can't run as a normal GitHub
Actions job - it has to execute from a real residential IP, i.e. this
machine. See DEPLOYMENT.md.

What a run leaves behind (Task Scheduler keeps no output of its own):
  logs/refresh_runs.jsonl   one line per run: step-by-step ok/fail, timing,
                            the tail of a failed step's output. Committed
                            and pushed with data/last_updated.json, so run
                            history is checkable by reading the repo. The
                            push result goes in a second line after the
                            commit, which the next run's commit carries.
  logs/runs/<run_at>/       the full output of every step (not committed).
  logs/refresh.lock         held while a run is going; stops a second one.

Usage:
    python scripts/weekly_refresh.py
    python scripts/weekly_refresh.py --no-publish   # dry run: build the copy,
        run every step, report, delete the copy. No swap, upload or commit.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
import time
import traceback
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
from core import paths
from core.constants import PBP_MAX_NEW_GAMES_PER_RUN
from scripts.season_teams import current_season_and_teams

LOG_PATH = paths.logs_dir() / "refresh_runs.jsonl"
RUNS_DIR = paths.logs_dir() / "runs"
LOCK_PATH = paths.logs_dir() / "refresh.lock"
# Far longer than a run ever takes (minutes), so a lock this old was left by
# a run that was killed without reaching its finally block.
LOCK_STALE_SECONDS = 6 * 3600
RELEASE_TAG = "data-v1"  # reused indefinitely so WAREHOUSE_URL never changes
PYTHON = sys.executable
# Task Scheduler launches this with the venv's python.exe directly (not an
# activated shell), so the venv's Scripts/ dir isn't on child processes'
# PATH - resolve dbt's full path the same way sys.executable resolves python.
DBT = str(Path(PYTHON).parent / ("dbt.exe" if os.name == "nt" else "dbt"))

# A hung step (a stalled API call, a locked file) must not hold the lock and
# the copy forever. Generous on purpose: these are "something is stuck"
# limits, not performance targets.
STEP_TIMEOUT_SECONDS = {"ingest": 3600, "payroll": 1800, "dbt_build": 1800}
DEFAULT_STEP_TIMEOUT_SECONDS = 900
ERROR_TAIL_CHARS = 2000
GIT_TIMEOUT_SECONDS = 300

log = logging.getLogger("weekly_refresh")


# -- steps ----------------------------------------------------------------------


def _since(started: float) -> float:
    return round(time.monotonic() - started, 1)


def _display(path: Path) -> str:
    """A log path as the run log records it: repo-relative when it can be."""
    try:
        return path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(path)


def run_step(
    name: str, cmd: list[str], *, warehouse: Path, log_dir: Path, cwd: Path | None = None
) -> dict:
    """Run one child process against `warehouse`; return its run-log entry.

    Its stdout and stderr both go, interleaved, to log_dir/<name>.log, and a
    failure's "error" is the tail of that file - dbt reports its errors on
    stdout, so stderr alone would often say nothing.
    """
    log.info("-> %s", name)
    timeout = STEP_TIMEOUT_SECONDS.get(name, DEFAULT_STEP_TIMEOUT_SECONDS)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{name}.log"
    env = {
        **os.environ,
        # Every child gets the file being built, so dbt (which reads
        # BIP_WAREHOUSE through its profile) and the scripts agree on it.
        "BIP_WAREHOUSE": str(warehouse),
        # The output goes to a file, which Python would otherwise block-buffer:
        # a step killed on timeout would lose exactly the lines that explain it.
        "PYTHONUNBUFFERED": "1",
        "PYTHONIOENCODING": "utf-8",
    }
    started = time.monotonic()
    with log_path.open("wb") as out:
        try:
            result = subprocess.run(
                cmd,
                cwd=cwd or PROJECT_ROOT,
                env=env,
                stdout=out,
                stderr=subprocess.STDOUT,
                timeout=timeout,
            )
            reason = None if result.returncode == 0 else f"exit code {result.returncode}"
        except subprocess.TimeoutExpired:
            reason = f"timed out after {timeout}s"
        except OSError as exc:
            # e.g. the executable itself couldn't be found/launched - still a
            # real failure worth logging, not a reason to crash silently.
            reason = f"could not launch {cmd[0]!r}: {exc}"
    entry: dict[str, Any] = {
        "step": name,
        "ok": reason is None,
        "seconds": _since(started),
        "log": _display(log_path),
    }
    if reason is not None:
        tail = log_path.read_text(encoding="utf-8", errors="replace")[-ERROR_TAIL_CHARS:]
        entry["error"] = f"{reason}\n{tail}" if tail.strip() else reason
    if entry["ok"]:
        log.info("   OK (%ss)", entry["seconds"])
    else:
        log.error("   FAIL: %s (%ss), output in %s", reason, entry["seconds"], log_path)
    return entry


def run_steps(run: dict, steps: list[tuple], *, warehouse: Path, log_dir: Path) -> bool:
    """Run steps in order, recording each one; stop at the first failure."""
    for name, cmd, cwd in steps:
        entry = run_step(name, cmd, warehouse=warehouse, log_dir=log_dir, cwd=cwd)
        run["steps"].append(entry)
        if not entry["ok"]:
            return False
    return True


def payroll_steps(warehouse: Path) -> list[tuple]:
    """The payroll fetch, plus the reload that lands its output in the warehouse.

    Built at call time, not as a module-level constant, because the season and
    team list come from raw.team_game_logs - which only reflects this run's
    ingestion once "load_duckdb" has run, and only in the copy being built
    (`warehouse`), not the real file. Computed any earlier, the first
    refresh after a season rollover would derive the *previous* season's teams,
    re-fetch ~30 already-static pages and skip the new season's payroll
    entirely until the following week. Deferring it also means importing this
    module no longer touches the database, so a fresh checkout with no
    warehouse yet can still bootstrap itself from nothing.
    """
    season, teams = current_season_and_teams(warehouse)
    return [
        (
            "payroll",
            [
                PYTHON,
                "ingestion/team_payroll_ingest.py",
                "--force",
                "--season",
                season,
                "--teams",
                *teams,
            ],
            None,
        ),
        # load_to_duckdb again: the payroll parquet was written after the first
        # load, and dbt runs next - without this it would query a warehouse a
        # week behind the file on disk.
        ("load_payroll", [PYTHON, "scripts/load_to_duckdb.py"], None),
    ]


def build(run: dict, warehouse: Path, log_dir: Path) -> bool:
    """Run every pipeline step against `warehouse` (the copy).

    Returns whether every required step passed; the two non-fatal steps'
    results go in run["payroll_ok"] / run["player_impact_ok"].
    """
    dbt_dir = PROJECT_ROOT / "dbt" / "basketball_intelligence"
    where = {"warehouse": warehouse, "log_dir": log_dir}

    ok = run_steps(
        run,
        [
            (
                "ingest",
                [
                    PYTHON,
                    "ingestion/nba_ingest.py",
                    "--force",
                    "--pbp-games",
                    str(PBP_MAX_NEW_GAMES_PER_RUN),
                ],
                None,
            ),
            ("load_duckdb", [PYTHON, "scripts/load_to_duckdb.py"], None),
        ],
        **where,
    )

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
    if ok:
        try:
            steps = payroll_steps(warehouse)
        # Broad on purpose: record the failure rather than crash the run.
        except Exception as exc:
            run["steps"].append(
                {
                    "step": "payroll",
                    "ok": False,
                    "seconds": 0.0,
                    "error": f"could not derive the current season/teams: {exc}",
                }
            )
            run["payroll_ok"] = False
        else:
            run["payroll_ok"] = run_steps(run, steps, **where)

    # One `dbt build` rather than seed/run/test: it runs each model's tests
    # right after the model, so a model that fails its tests stops the
    # models built on top of it instead of everything being built first and
    # tested after.
    if ok:
        ok = run_steps(
            run, [("dbt_build", [DBT, "build", "--profiles-dir", "."], dbt_dir)], **where
        )

    # The player-impact refit is NON-FATAL too, for the same reason as
    # payroll. It only feeds the Arcade team builder; the predictions and
    # everything else on the site never read it. ml.player_impact.write()
    # replaces both of its tables in one transaction, so a failed refit
    # leaves last week's tables in place, which the Arcade is perfectly
    # happy to keep using. Blocking predictions and the release publish on
    # a game's player ratings would be the worse outage.
    if ok:
        run["player_impact_ok"] = run_steps(
            run, [("player_impact", [PYTHON, "-m", "ml.player_impact"], None)], **where
        )

    if ok:
        ok = run_steps(
            run,
            [
                ("predict", [PYTHON, "-m", "ml.predict"], None),
                ("score_predictions", [PYTHON, "-m", "ml.evaluate"], None),
                ("write_metadata", [PYTHON, "scripts/write_metadata.py"], None),
            ],
            **where,
        )
    return ok


# -- the copy -----------------------------------------------------------------


def next_path(warehouse: Path) -> Path:
    """The copy a run builds: warehouse/basketball.duckdb ->
    warehouse/next/basketball.duckdb.

    The same file name, in a folder of its own: dbt-duckdb names the catalog
    after the file stem and bakes it into every view it creates ("FROM
    basketball.raw.players"), so a copy called anything else would hold views
    that stop resolving the moment it is renamed onto the warehouse. A
    subfolder keeps it on the same filesystem, so os.replace onto the real
    file is still a single atomic rename.
    """
    return warehouse.parent / "next" / warehouse.name


def wal_path(db: Path) -> Path:
    """DuckDB's write-ahead log for a database file."""
    return db.with_name(db.name + ".wal")


def discard(copy: Path) -> None:
    """Delete the copy, its WAL and its folder, if there are any."""
    for path in (copy, wal_path(copy)):
        path.unlink(missing_ok=True)
    # Only if empty: never take anything else that ended up in there with it.
    if copy.parent.exists() and not any(copy.parent.iterdir()):
        copy.parent.rmdir()


def prepare_copy(warehouse: Path, copy: Path) -> str | None:
    """Start the copy from the current warehouse (or from nothing, on a fresh
    checkout, where load_duckdb creates it); an error, or None."""
    try:
        discard(copy)  # leftovers of a run that was killed mid-build
        copy.parent.mkdir(parents=True, exist_ok=True)
        if warehouse.exists():
            # copyfile, not copy2: a fresh mtime, since health_check reads
            # the warehouse's age from it.
            shutil.copyfile(warehouse, copy)
            # Writes still only in the warehouse's WAL are part of it too.
            if wal_path(warehouse).exists():
                shutil.copyfile(wal_path(warehouse), wal_path(copy))
    except OSError as exc:
        return f"could not copy {warehouse} to {copy}: {exc}"
    return None


def swap(copy: Path, warehouse: Path) -> str | None:
    """Move the finished copy onto the real warehouse; an error, or None.

    DuckDB keeps recent writes in <file>.wal until a checkpoint folds them
    into the file. Every step has exited by now and a clean close normally
    checkpoints, but if a WAL is still beside the copy it is folded in here,
    so the file that gets renamed - and uploaded - is complete on its own.
    A WAL left beside the *real* warehouse belongs to the old file: replayed
    onto the new one it would corrupt it, so it is removed - but only after
    the replace succeeded, since until then it is still the old file's.
    """
    try:
        if wal_path(copy).exists():
            con = duckdb.connect(str(copy))
            try:
                con.execute("CHECKPOINT")
            finally:
                con.close()
        if wal_path(copy).exists():
            return f"{wal_path(copy)} survived a checkpoint; not swapping in a partial file"
        copy.replace(warehouse)  # os.replace: atomic, same folder
    except (OSError, duckdb.Error) as exc:
        # On Windows the usual cause is a process holding the warehouse open
        # (a local `streamlit run` of the dashboard, a DuckDB shell).
        return (
            f"could not replace {warehouse} with the new build: {exc}. "
            "Close the dashboard or anything else that has the warehouse "
            "open and rerun; the warehouse was left as it was."
        )
    try:
        wal_path(warehouse).unlink(missing_ok=True)
    except OSError as exc:
        return (
            f"swapped in the new warehouse but could not remove the old "
            f"{wal_path(warehouse)} ({exc}); delete it by hand before opening "
            "the warehouse"
        )
    return None


def timed(run: dict, name: str, action: Callable[[], str | None]) -> bool:
    """Record a step that is a function call rather than a child process.

    `action` returns an error message, or None for success.
    """
    log.info("-> %s", name)
    started = time.monotonic()
    error = action()
    entry: dict[str, Any] = {"step": name, "ok": error is None, "seconds": _since(started)}
    if error is not None:
        entry["error"] = error
        log.error("   FAIL: %s", error)
    else:
        log.info("   OK (%ss)", entry["seconds"])
    run["steps"].append(entry)
    return error is None


# -- publishing ---------------------------------------------------------------


def publish(run: dict, warehouse: Path, log_dir: Path) -> bool:
    """Upload the swapped-in warehouse, then the version marker.

    In that order on purpose: the live app re-downloads when version.txt
    changes, so the marker must never move before the data it announces.
    version.txt is written only once the warehouse is up, and put back the
    way it was if its own upload fails.
    """
    where = {"warehouse": warehouse, "log_dir": log_dir}
    # The real path, never the copy: gh names the asset after the file, and
    # the app downloads .../releases/download/data-v1/basketball.duckdb.
    upload = ["gh", "release", "upload", RELEASE_TAG]
    if not run_steps(
        run, [("publish_release", [*upload, str(warehouse), "--clobber"], None)], **where
    ):
        return False

    version_path = paths.release_version_path()
    previous = version_path.read_text() if version_path.exists() else None
    version_path.write_text(datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))
    if run_steps(
        run, [("publish_version", [*upload, str(version_path), "--clobber"], None)], **where
    ):
        return True
    if previous is None:
        version_path.unlink(missing_ok=True)
    else:
        version_path.write_text(previous)
    return False


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT_SECONDS,
    )


def commit_status(run_ok: bool, payroll_ok: bool | None, player_impact_ok: bool | None) -> str:
    """The status word for the refresh commit message.

    A non-fatal step that failed (False, not None = never attempted) is
    named in it, so a run that is "ok" overall still says what it carried
    over from last week.
    """
    if not run_ok:
        return "FAILED"
    failed = [
        name
        for name, step_ok in (("payroll", payroll_ok), ("player_impact", player_impact_ok))
        if step_ok is False
    ]
    if not failed:
        return "ok"
    noun = "step" if len(failed) == 1 else "steps"
    return f"ok ({' and '.join(failed)} {noun} failed)"


def commit_and_push(run: dict) -> dict:
    """Commit this run's log line and data/last_updated.json, and push.

    Returns a "git_push" entry. It cannot go in the run's own line, which
    has to be written before the commit that carries it; the caller appends
    it as a line of its own, which reaches GitHub with the next run's commit.
    A failed push does not change the exit code: the release is already
    published, and the commit is pushed along with the next one.
    """
    started = time.monotonic()
    error = None
    try:
        status = commit_status(run["ok"], run["payroll_ok"], run["player_impact_ok"])
        add = git("add", "data/last_updated.json", "logs/refresh_runs.jsonl")
        if add.returncode != 0:
            error = f"git add failed: {add.stdout}{add.stderr}"
        elif git("diff", "--cached", "--quiet").returncode != 0:
            commit = git("commit", "-m", f"Weekly refresh: {status} {run['run_at']}")
            if commit.returncode != 0:
                error = f"git commit failed: {commit.stdout}{commit.stderr}"
            else:
                push = git("push")
                if push.returncode != 0:
                    error = f"git push failed: {push.stdout}{push.stderr}"
    except (OSError, subprocess.SubprocessError) as exc:
        error = f"git did not run: {exc}"
    entry: dict[str, Any] = {
        "run_at": run["run_at"],
        "step": "git_push",
        "ok": error is None,
        "seconds": _since(started),
    }
    if error is not None:
        entry["error"] = error[-ERROR_TAIL_CHARS:]
        log.error("git: %s", error)
    else:
        log.info("Committed and pushed the run log")
    return entry


def append_log(record: dict) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


# -- the lock -------------------------------------------------------------------


def acquire_lock() -> bool:
    """Create LOCK_PATH, or say why not. A lock older than LOCK_STALE_SECONDS
    was left by a killed run and is taken over."""
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        try:
            fd = os.open(LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                age = time.time() - LOCK_PATH.stat().st_mtime
                holder = LOCK_PATH.read_text(errors="replace").strip()
            except FileNotFoundError:
                continue  # released between the two calls; try again
            if age < LOCK_STALE_SECONDS:
                log.error(
                    "Another refresh is running (%s, lock %.0f min old); exiting. "
                    "If it is not, delete %s.",
                    holder,
                    age / 60,
                    LOCK_PATH,
                )
                return False
            log.warning("Taking over a stale lock (%s, %.1f h old)", holder, age / 3600)
            LOCK_PATH.unlink(missing_ok=True)
            continue
        with os.fdopen(fd, "w") as f:
            json.dump({"pid": os.getpid(), "started_at": datetime.now(UTC).isoformat()}, f)
        return True
    log.error("Could not take %s; exiting.", LOCK_PATH)
    return False


def release_lock() -> None:
    """Remove LOCK_PATH if it is still this process's (a run that ran past
    the stale limit may have had it taken over)."""
    try:
        if json.loads(LOCK_PATH.read_text()).get("pid") == os.getpid():
            LOCK_PATH.unlink()
    except (OSError, ValueError) as exc:
        log.warning("Could not release %s: %s", LOCK_PATH, exc)


# -- main -------------------------------------------------------------------------


def refresh(publishing: bool) -> int:
    """One run, start to finish; returns the exit code."""
    started = datetime.now(UTC)
    run: dict[str, Any] = {"run_at": started.isoformat(timespec="seconds")}
    if not publishing:
        run["dry_run"] = True
    run.update({"steps": [], "payroll_ok": None, "player_impact_ok": None, "ok": False})
    log_dir = RUNS_DIR / started.strftime("%Y%m%dT%H%M%SZ")
    warehouse = paths.warehouse_path()
    copy = next_path(warehouse)
    log.info("Refresh %s%s: building %s", run["run_at"], "" if publishing else " (dry run)", copy)

    ok = False
    try:
        ok = timed(run, "copy_warehouse", lambda: prepare_copy(warehouse, copy))
        ok = ok and build(run, copy, log_dir)
        if ok and publishing:
            ok = timed(run, "swap", lambda: swap(copy, warehouse))
            ok = ok and publish(run, warehouse, log_dir)
    # Broad on purpose: a bug or a full disk here must still leave a run log
    # line saying so, and be committed like any other failure.
    except Exception:
        log.exception("Refresh crashed")
        run["steps"].append(
            {
                "step": "crashed",
                "ok": False,
                "seconds": 0.0,
                "error": traceback.format_exc()[-ERROR_TAIL_CHARS:],
            }
        )
        ok = False
    finally:
        run["ok"] = ok
        # After a swap there is nothing left to delete; after a failure or a
        # dry run this is the whole cleanup - the real warehouse was never
        # touched.
        try:
            discard(copy)
        except OSError as exc:
            log.warning("Could not delete %s (%s); the next run replaces it", copy, exc)
        append_log(run)

    failed = [s["step"] for s in run["steps"] if not s["ok"]]
    log.info(
        "Refresh %s%s; step logs in %s",
        commit_status(ok, run["payroll_ok"], run["player_impact_ok"]),
        f" (failed: {', '.join(failed)})" if failed else "",
        log_dir,
    )
    if publishing:
        append_log(commit_and_push(run))
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--no-publish",
        action="store_true",
        help="dry run: build and check the copy, then delete it (no swap, upload or commit)",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )
    # A --no-publish run takes the lock too: it rewrites the same copy and
    # raw files a scheduled run would be using.
    if not acquire_lock():
        sys.exit(2)
    try:
        code = refresh(publishing=not args.no_publish)
    finally:
        release_lock()
    sys.exit(code)


if __name__ == "__main__":
    main()
