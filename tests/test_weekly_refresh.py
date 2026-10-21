"""The weekly refresh: which failures stop the run, that the warehouse is
built in a copy and only swapped in after every required step passed, the
release/version ordering, the lock and the run log. No real subprocess,
network or git runs here - subprocess.Popen/run and sleeps are faked, and
the warehouse, logs and version file all live in a temp folder."""

import json
import os
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

import duckdb
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import weekly_refresh as wr

OLD, NEW = b"old warehouse", b"new warehouse"


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A temp warehouse holding OLD, temp logs, and a faked payroll step list."""
    warehouse = tmp_path / "warehouse" / "basketball.duckdb"
    warehouse.parent.mkdir()
    warehouse.write_bytes(OLD)
    logs = tmp_path / "logs"
    monkeypatch.delenv("BIP_DATA_HOME", raising=False)
    monkeypatch.setenv("BIP_WAREHOUSE", str(warehouse))
    monkeypatch.setattr(wr, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(wr, "LOG_PATH", logs / "refresh_runs.jsonl")
    monkeypatch.setattr(wr, "LOCK_PATH", logs / "refresh.lock")
    monkeypatch.setattr(wr, "RUNS_DIR", logs / "runs")
    monkeypatch.setattr(wr, "LAUNCH_LOG_PATH", logs / "refresh.log")
    sleeps: list[float] = []
    monkeypatch.setattr(wr.time, "sleep", sleeps.append)
    monkeypatch.setattr(
        wr,
        "payroll_steps",
        lambda warehouse: [("payroll", ["payroll"], None), ("load_payroll", ["load"], None)],
    )
    return {
        "warehouse": warehouse,
        "copy": warehouse.parent / "next" / "basketball.duckdb",
        "version": warehouse.parent / "version.txt",
        "logs": logs,
        "sleeps": sleeps,
    }


@pytest.fixture
def fake_run(env, monkeypatch):
    """Run main() with a fake subprocess.Popen/run; returns what happened.

    Each step is identified by the log file its output goes to. The fake
    "load_duckdb" writes NEW into whatever BIP_WAREHOUSE it was handed, the
    way the real load writes into the copy.
    """

    def go(
        *failing: str,
        timeouts: tuple[str, ...] = (),
        argv: tuple[str, ...] = (),
        git_fails: dict[str, str] | None = None,
        output: dict[str, str] | None = None,
        after: dict[str, Callable[[Path], None]] | None = None,
    ) -> dict:
        ran: list[str] = []
        calls: dict[str, dict] = {}
        uploads: list[dict] = []
        git_calls: list[tuple[str, ...]] = []
        commits: list[str] = []
        killed: list[list[str]] = []

        class FakePopen:
            pid = 4242

            def __init__(self, cmd, **kwargs):
                self.name = name = Path(kwargs["stdout"].name).stem
                self.returncode: int | None = None
                ran.append(name)
                calls[name] = {"cmd": cmd, **kwargs}
                out = kwargs["stdout"]
                out.write(f"running {name}\n".encode())
                if cmd[0] == "gh":
                    uploads.append(
                        {
                            "step": name,
                            "files": [Path(c) for c in cmd[4:-1]],
                            "warehouse": env["warehouse"].read_bytes(),
                            "version": env["version"].read_text()
                            if env["version"].exists()
                            else None,
                        }
                    )
                if name in timeouts:
                    return
                if name == "load_duckdb":
                    Path(kwargs["env"]["BIP_WAREHOUSE"]).write_bytes(NEW)
                if output and name in output:
                    out.write(output[name].encode())
                if after and name in after:
                    after[name](Path(kwargs["env"]["BIP_WAREHOUSE"]))
                self.returncode = 1 if name in failing else 0

            def communicate(self, timeout=None):
                calls[self.name]["timeout"] = timeout
                if self.returncode is None:
                    raise subprocess.TimeoutExpired(calls[self.name]["cmd"], timeout)
                return None, None

            def kill(self):
                self.returncode = -9

            def wait(self, timeout=None):
                return self.returncode

        def fake_subprocess_run(cmd, **kwargs):
            if cmd[0] == "taskkill":
                killed.append(cmd)
                return subprocess.CompletedProcess(cmd, 0, "", "")
            assert cmd[0] == "git", cmd
            args = tuple(cmd[1:])
            git_calls.append(args)
            if args[0] == "commit":
                commits.append(args[2])
            if git_fails and args[0] in git_fails:
                return subprocess.CompletedProcess(cmd, 1, "", git_fails[args[0]])
            # "diff --cached --quiet" exits 1 when something is staged
            return subprocess.CompletedProcess(cmd, 1 if args[0] == "diff" else 0, "", "")

        monkeypatch.setattr(wr.subprocess, "Popen", FakePopen)
        monkeypatch.setattr(wr.subprocess, "run", fake_subprocess_run)
        # never a real SIGKILL to a real process group on POSIX
        monkeypatch.setattr(
            wr.os, "killpg", lambda pid, sig: killed.append(["killpg", str(pid)]), raising=False
        )
        with pytest.raises(SystemExit) as exit_info:
            wr.main(list(argv))
        log_path = env["logs"] / "refresh_runs.jsonl"
        lines = [json.loads(line) for line in log_path.read_text().splitlines()]
        return {
            "ran": ran,
            "calls": calls,
            "uploads": uploads,
            "git": git_calls,
            "commits": commits,
            "killed": killed,
            "lines": lines,
            "run": lines[0],
            "exit": exit_info.value.code,
        }

    return go


def test_a_clean_run_publishes_and_commits_ok(fake_run):
    out = fake_run()
    assert out["exit"] == 0
    assert out["run"]["ok"] is True
    assert out["run"]["player_impact_ok"] is True
    assert out["run"]["payroll_ok"] is True
    assert "publish_release" in out["ran"]
    assert out["commits"][0].startswith("Weekly refresh: ok ")
    assert ("push",) in out["git"]


def test_the_commit_carries_the_predictions_history(fake_run):
    out = fake_run()
    add = next(args for args in out["git"] if args[0] == "add")
    assert "data/predictions/history.csv" in add
    assert "data/last_updated.json" in add
    assert "logs/refresh_runs.jsonl" in add


def test_dbt_runs_as_one_build_step(fake_run):
    out = fake_run()
    assert "dbt_build" in out["ran"]
    assert not {"dbt_seed", "dbt_run", "dbt_test"} & set(out["ran"])
    assert out["calls"]["dbt_build"]["cmd"][1:] == ["build", "--profiles-dir", "."]


def test_the_ingest_step_passes_the_shared_play_by_play_cap(fake_run):
    from core.constants import PBP_MAX_NEW_GAMES_PER_RUN

    argv = fake_run()["calls"]["ingest"]["cmd"]
    assert argv[argv.index("--pbp-games") + 1] == str(PBP_MAX_NEW_GAMES_PER_RUN)


def test_a_failed_player_impact_step_does_not_stop_the_run(fake_run):
    out = fake_run("player_impact")
    ran = out["ran"]
    # everything after it still runs, including the release publish
    for step in ("predict", "score_predictions", "write_metadata", "publish_release"):
        assert step in ran, step
    assert ran.index("player_impact") < ran.index("predict")
    assert out["exit"] == 0
    assert out["run"]["ok"] is True
    assert out["run"]["player_impact_ok"] is False
    failed = [s["step"] for s in out["run"]["steps"] if not s["ok"]]
    assert failed == ["player_impact"]
    assert out["commits"][0].startswith("Weekly refresh: ok (player_impact step failed) ")


def test_payroll_and_player_impact_failures_are_both_named(fake_run):
    out = fake_run("payroll", "player_impact")
    assert out["exit"] == 0
    assert out["run"]["payroll_ok"] is False
    assert out["run"]["player_impact_ok"] is False
    assert out["commits"][0].startswith(
        "Weekly refresh: ok (payroll and player_impact steps failed) "
    )


def test_a_dbt_failure_is_still_fatal_and_skips_player_impact(fake_run):
    out = fake_run("dbt_build")
    assert out["exit"] == 1
    assert out["run"]["ok"] is False
    assert out["run"]["player_impact_ok"] is None  # never attempted
    assert "player_impact" not in out["ran"]
    assert "publish_release" not in out["ran"]
    assert out["commits"][0].startswith("Weekly refresh: FAILED ")


def test_commit_status_wording():
    assert wr.commit_status(True, True, True) == "ok"
    assert wr.commit_status(True, None, None) == "ok"
    assert wr.commit_status(True, False, True) == "ok (payroll step failed)"
    assert wr.commit_status(True, True, False) == "ok (player_impact step failed)"
    assert wr.commit_status(False, False, None) == "FAILED"


# -- building in a copy ------------------------------------------------------


def test_every_child_step_builds_into_the_copy(fake_run, env):
    out = fake_run()
    for name, call in out["calls"].items():
        if name.startswith("publish_"):
            continue
        assert call["env"]["BIP_WAREHOUSE"] == str(env["copy"]), name
        # the rest of the environment is passed through
        assert call["env"]["PATH"] == os.environ["PATH"]


def test_the_copy_keeps_the_warehouse_file_name():
    # dbt-duckdb names the catalog after the file stem and writes it into
    # every view ("FROM basketball.raw.players"): a copy with any other stem
    # would hold views that break once it is renamed onto the warehouse.
    warehouse = Path("somewhere") / "warehouse" / "basketball.duckdb"
    copy = wr.next_path(warehouse)
    assert copy.name == warehouse.name
    assert copy.parent.parent == warehouse.parent  # same filesystem: atomic rename


def test_the_copy_folder_is_removed_with_the_copy(fake_run, env):
    fake_run("dbt_build")
    assert not env["copy"].parent.exists()
    fake_run()
    assert not env["copy"].parent.exists()


def test_the_copy_is_swapped_in_only_on_success(fake_run, env):
    out = fake_run()
    assert env["warehouse"].read_bytes() == NEW
    assert not env["copy"].exists()
    assert [s["step"] for s in out["run"]["steps"]][:2] == ["copy_warehouse", "ingest"]
    assert "swap" in [s["step"] for s in out["run"]["steps"]]


def test_a_failure_leaves_the_warehouse_untouched_and_deletes_the_copy(fake_run, env):
    out = fake_run("dbt_build")
    assert env["warehouse"].read_bytes() == OLD
    assert not env["copy"].exists()
    assert out["uploads"] == []
    assert not env["version"].exists()


def test_a_leftover_copy_from_a_killed_run_is_replaced(fake_run, env):
    env["copy"].parent.mkdir()
    env["copy"].write_bytes(b"half-built leftovers")
    fake_run("ingest")  # fails before anything writes into the copy
    assert env["warehouse"].read_bytes() == OLD
    assert not env["copy"].exists()


def test_a_fresh_checkout_with_no_warehouse_builds_one(fake_run, env):
    env["warehouse"].unlink()
    out = fake_run()
    assert out["exit"] == 0
    assert env["warehouse"].read_bytes() == NEW


def test_a_failed_swap_is_recorded_and_nothing_is_published(fake_run, env, monkeypatch):
    def locked(src, dst):
        raise PermissionError(32, "The process cannot access the file")

    monkeypatch.setattr(wr.os, "replace", locked)
    out = fake_run()
    assert out["exit"] == 1
    assert out["run"]["ok"] is False
    (swap,) = [s for s in out["run"]["steps"] if s["step"] == "swap"]
    assert swap["ok"] is False
    assert "close the dashboard" in swap["error"].lower()
    assert env["warehouse"].read_bytes() == OLD
    assert not env["copy"].exists()
    assert out["uploads"] == []
    assert out["commits"][0].startswith("Weekly refresh: FAILED ")


def _duckdb_with_wal(path: Path, value: int) -> None:
    """A real DuckDB file whose last write is still only in its .wal."""
    con = duckdb.connect(str(path))
    con.execute("PRAGMA disable_checkpoint_on_shutdown")
    con.execute(f"CREATE OR REPLACE TABLE t AS SELECT {value} AS x")
    con.close()


def test_the_copy_wal_is_checkpointed_and_a_stale_wal_removed(fake_run, env):
    env["warehouse"].unlink()
    _duckdb_with_wal(env["warehouse"], 1)  # a stale .wal beside the real file
    assert wr.wal_path(env["warehouse"]).exists()

    def load_leaves_a_wal(copy: Path) -> None:
        for path in (copy, wr.wal_path(copy)):
            path.unlink(missing_ok=True)
        _duckdb_with_wal(copy, 2)

    out = fake_run(after={"load_duckdb": load_leaves_a_wal})
    assert out["exit"] == 0
    assert not wr.wal_path(env["warehouse"]).exists()
    assert not wr.wal_path(env["copy"]).exists()
    con = duckdb.connect(str(env["warehouse"]), read_only=True)
    assert con.execute("SELECT x FROM t").fetchone() == (2,)
    con.close()


# -- steps: timeouts and logs -------------------------------------------------


def test_a_timeout_is_recorded_as_a_failure(fake_run, env):
    out = fake_run(timeouts=("ingest",))
    assert out["exit"] == 1
    (ingest,) = [s for s in out["run"]["steps"] if s["step"] == "ingest"]
    assert ingest["ok"] is False
    assert "timed out after 3600s" in ingest["error"]
    assert env["warehouse"].read_bytes() == OLD
    if sys.platform == "win32":
        assert out["killed"] == [["taskkill", "/T", "/F", "/PID", "4242"]]
    else:
        assert out["killed"] == [["killpg", "4242"]]


def test_each_step_has_its_own_timeout(fake_run):
    calls = fake_run()["calls"]
    assert calls["ingest"]["timeout"] == 3600
    assert calls["payroll"]["timeout"] == 1800
    assert calls["dbt_build"]["timeout"] == 1800
    assert calls["predict"]["timeout"] == 900


def test_each_step_keeps_a_full_log_and_the_error_tail_includes_stdout(fake_run, env):
    out = fake_run("dbt_build", output={"dbt_build": "Compilation Error in model foo\n"})
    (dbt,) = [s for s in out["run"]["steps"] if s["step"] == "dbt_build"]
    assert "Compilation Error in model foo" in dbt["error"]
    log_file = env["logs"].parent / dbt["log"]
    assert log_file.parent.parent == env["logs"] / "runs"
    assert ":" not in log_file.parent.name  # filesystem-safe run folder
    assert "running dbt_build" in log_file.read_text()
    for step in out["run"]["steps"]:
        if step["step"] not in ("copy_warehouse", "swap"):
            assert "log" in step, step


def test_an_unexpected_error_still_writes_the_run_log(fake_run, monkeypatch, env):
    def broken(*a, **k):
        raise RuntimeError("bug in the refresh itself")

    monkeypatch.setattr(wr, "payroll_steps", broken)
    monkeypatch.setattr(wr, "prepare_copy", broken)
    out = fake_run()
    assert out["exit"] == 1
    assert out["run"]["ok"] is False
    assert "bug in the refresh itself" in json.dumps(out["run"])
    assert not (env["logs"] / "refresh.lock").exists()


# -- publishing ---------------------------------------------------------------


def test_the_warehouse_is_uploaded_after_the_swap_then_the_version(fake_run, env):
    env["version"].write_text("v-old")
    out = fake_run()
    first, second = out["uploads"]
    # the real path, so the asset keeps the name the live app downloads
    assert first["files"] == [env["warehouse"]]
    assert first["warehouse"] == NEW
    assert first["version"] == "v-old"  # not written until the upload succeeded
    assert second["files"] == [env["version"]]
    assert second["version"] != "v-old"
    assert env["version"].read_text() == second["version"]


def test_a_failed_warehouse_upload_leaves_the_version_alone(fake_run, env):
    env["version"].write_text("v-old")
    out = fake_run("publish_release")
    assert out["exit"] == 1
    assert len(out["uploads"]) == 1
    assert env["version"].read_text() == "v-old"


def test_a_failed_version_upload_restores_the_previous_version(fake_run, env):
    env["version"].write_text("v-old")
    out = fake_run("publish_version")
    assert out["exit"] == 1
    assert env["version"].read_text() == "v-old"


def test_a_failed_version_upload_removes_a_version_that_did_not_exist(fake_run, env):
    fake_run("publish_version")
    assert not env["version"].exists()


# -- git ------------------------------------------------------------------------


def test_the_push_result_is_a_second_log_line(fake_run):
    out = fake_run()
    run, push = out["lines"]
    assert push["run_at"] == run["run_at"]
    assert push["step"] == "git_push"
    assert push["ok"] is True


def test_a_git_push_failure_is_recorded(fake_run):
    out = fake_run(git_fails={"push": "! [rejected] main -> main (fetch first)"})
    push = out["lines"][1]
    assert push["ok"] is False
    assert "rejected" in push["error"]
    # the refresh itself succeeded and was published
    assert out["run"]["ok"] is True


def test_a_git_commit_failure_is_recorded_and_nothing_pushed(fake_run):
    out = fake_run(git_fails={"commit": "Author identity unknown"})
    push = out["lines"][1]
    assert push["ok"] is False
    assert "Author identity unknown" in push["error"]
    assert ("push",) not in out["git"]


# -- --no-publish ---------------------------------------------------------------


def test_no_publish_touches_nothing(fake_run, env):
    env["version"].write_text("v-old")
    out = fake_run(argv=("--no-publish",))
    assert out["exit"] == 0
    for step in ("ingest", "dbt_build", "write_metadata"):
        assert step in out["ran"], step
    assert env["warehouse"].read_bytes() == OLD
    assert not env["copy"].exists()
    assert env["version"].read_text() == "v-old"
    assert out["uploads"] == []
    assert out["git"] == []
    assert out["run"]["dry_run"] is True
    assert "swap" not in [s["step"] for s in out["run"]["steps"]]
    assert len(out["lines"]) == 1  # no git_push line


def test_no_publish_tells_every_step_it_is_a_dry_run(fake_run):
    # ml.predict still writes the copy's table but leaves the committed
    # history CSV alone: a dry run must not leave rows for the next real
    # run to commit.
    out = fake_run(argv=("--no-publish",))
    for name, call in out["calls"].items():
        assert call["env"]["BIP_DRY_RUN"] == "1", name


def test_a_publishing_run_is_never_a_dry_run(fake_run, monkeypatch):
    # Not even with BIP_DRY_RUN left over in the shell: the predictions this
    # run publishes must reach the history.
    monkeypatch.setenv("BIP_DRY_RUN", "1")
    out = fake_run()
    assert "BIP_DRY_RUN" not in out["calls"]["predict"]["env"]


# -- the lock -------------------------------------------------------------------


def test_the_lock_prevents_overlap(fake_run, env):
    lock = env["logs"] / "refresh.lock"
    lock.parent.mkdir(parents=True)
    lock.write_text(json.dumps({"pid": 99999, "started_at": "now"}))
    with pytest.raises(SystemExit) as exit_info:
        wr.main([])
    assert exit_info.value.code == 2
    assert lock.exists()  # still the other run's
    assert not (env["logs"] / "refresh_runs.jsonl").exists()
    assert env["warehouse"].read_bytes() == OLD


def test_a_stale_lock_is_taken_over(fake_run, env):
    lock = env["logs"] / "refresh.lock"
    lock.parent.mkdir(parents=True)
    lock.write_text(json.dumps({"pid": 99999, "started_at": "long ago"}))
    seven_hours_ago = time.time() - 7 * 3600
    os.utime(lock, (seven_hours_ago, seven_hours_ago))
    out = fake_run()
    assert out["exit"] == 0
    assert not lock.exists()


def test_the_lock_is_released_after_a_failed_run(fake_run, env):
    fake_run("ingest")
    assert not (env["logs"] / "refresh.lock").exists()


def test_payroll_steps_read_the_copy(monkeypatch, tmp_path):
    seen = []

    def fake_current(db_path):
        seen.append(db_path)
        return "2025-26", ["bos", "lal"]

    monkeypatch.setattr(wr, "current_season_and_teams", fake_current)
    steps = wr.payroll_steps(tmp_path / "copy.duckdb")
    assert seen == [tmp_path / "copy.duckdb"]
    assert steps[0][1][-3:] == ["--teams", "bos", "lal"]


# -- Windows file locks ------------------------------------------------------------


def _replace_failing(monkeypatch, times: int | None, seen: list | None = None):
    """os.replace raising PermissionError `times` times (None: always), then real."""
    real_replace = os.replace
    failures = {"left": times}

    def replace(src, dst):
        if seen is not None:
            seen.append((Path(src), Path(dst)))
        if failures["left"] is None or failures["left"] > 0:
            if failures["left"] is not None:
                failures["left"] -= 1
            raise PermissionError(32, "The process cannot access the file")
        return real_replace(src, dst)

    monkeypatch.setattr(wr.os, "replace", replace)


def test_the_swap_retries_while_the_warehouse_is_briefly_locked(fake_run, env, monkeypatch):
    _replace_failing(monkeypatch, 3)
    out = fake_run()
    assert out["exit"] == 0
    assert env["warehouse"].read_bytes() == NEW
    assert env["sleeps"] == [1, 2, 4]


def test_the_swap_gives_up_after_its_retries(fake_run, env, monkeypatch):
    _replace_failing(monkeypatch, None)
    out = fake_run()
    assert out["exit"] == 1
    assert env["sleeps"] == list(wr.FILE_LOCK_RETRY_DELAYS_SECONDS)
    (swap,) = [s for s in out["run"]["steps"] if s["step"] == "swap"]
    assert "close the dashboard" in swap["error"].lower()
    assert env["warehouse"].read_bytes() == OLD
    assert not env["copy"].exists()
    assert out["uploads"] == []


def test_discarding_the_copy_retries_while_it_is_locked(fake_run, env, monkeypatch):
    real_unlink = os.unlink
    failures = {"left": 2}

    def unlink(path, *a, **k):
        if Path(path) == env["copy"] and failures["left"]:
            failures["left"] -= 1
            raise PermissionError(32, "The process cannot access the file")
        return real_unlink(path, *a, **k)

    monkeypatch.setattr(wr.os, "unlink", unlink)
    out = fake_run(argv=("--no-publish",))
    assert out["exit"] == 0
    assert not env["copy"].exists()
    assert env["sleeps"] == [1, 2]


# prepare_copy copies the warehouse's WAL along with it; the steps' clean
# close folds it into the copy, which these fakes stand in for.
CLEAN_CLOSE = {"load_duckdb": lambda copy: wr.wal_path(copy).unlink(missing_ok=True)}


def test_a_stale_wal_is_moved_aside_before_the_replace(fake_run, env, monkeypatch):
    stale = wr.wal_path(env["warehouse"])
    stale.write_bytes(b"old wal")
    seen: list = []
    _replace_failing(monkeypatch, 0, seen)
    out = fake_run(after=CLEAN_CLOSE)
    assert out["exit"] == 0
    aside = stale.with_name(stale.name + ".stale")
    # first the WAL goes aside, then the copy goes onto the warehouse
    assert seen == [(stale, aside), (env["copy"], env["warehouse"])]
    assert not stale.exists() and not aside.exists()
    assert env["warehouse"].read_bytes() == NEW


def test_a_stale_wal_is_put_back_when_the_replace_fails(fake_run, env, monkeypatch):
    stale = wr.wal_path(env["warehouse"])
    stale.write_bytes(b"old wal")
    real_replace = os.replace

    def replace(src, dst):
        if Path(dst) == env["warehouse"]:
            raise PermissionError(32, "The process cannot access the file")
        return real_replace(src, dst)

    monkeypatch.setattr(wr.os, "replace", replace)
    out = fake_run(after=CLEAN_CLOSE)
    assert out["exit"] == 1
    (swap,) = [s for s in out["run"]["steps"] if s["step"] == "swap"]
    assert "close the dashboard" in swap["error"].lower()
    assert stale.read_bytes() == b"old wal"  # still the old file's
    assert not stale.with_name(stale.name + ".stale").exists()
    assert env["warehouse"].read_bytes() == OLD


# -- timeouts kill the whole tree ------------------------------------------------


class _Proc:
    pid = 4242

    def __init__(self):
        self.killed = False

    def kill(self):
        self.killed = True

    def wait(self, timeout=None):
        return -9


def test_kill_tree_uses_taskkill_on_windows(monkeypatch):
    runs = []
    monkeypatch.setattr(wr.sys, "platform", "win32")
    monkeypatch.setattr(
        wr.subprocess,
        "run",
        lambda cmd, **k: runs.append(cmd) or subprocess.CompletedProcess(cmd, 0),
    )
    proc = _Proc()
    wr.kill_tree(proc)  # type: ignore[arg-type]
    assert runs == [["taskkill", "/T", "/F", "/PID", "4242"]]
    assert proc.killed


def test_kill_tree_kills_the_process_group_elsewhere(monkeypatch):
    groups = []
    monkeypatch.setattr(wr.sys, "platform", "linux")
    monkeypatch.setattr(wr.os, "killpg", lambda pid, sig: groups.append((pid, sig)), raising=False)
    monkeypatch.setattr(wr.signal, "SIGKILL", 9, raising=False)
    proc = _Proc()
    wr.kill_tree(proc)  # type: ignore[arg-type]
    assert groups == [(4242, 9)]


# -- the refresh's own log -----------------------------------------------------------


def test_every_run_keeps_its_own_log(fake_run, env):
    out = fake_run()
    log_file = env["logs"].parent / out["run"]["log"]
    assert log_file.name == "refresh.log"
    assert log_file.parent.parent == env["logs"] / "runs"
    text = log_file.read_text(encoding="utf-8")
    for line in ("-> copy_warehouse", "-> ingest", "-> swap", "Committed and pushed"):
        assert line in text, line


def test_a_skipped_run_leaves_a_note_in_the_launch_log(fake_run, env):
    lock = env["logs"] / "refresh.lock"
    lock.parent.mkdir(parents=True)
    lock.write_text(json.dumps({"pid": 99999, "started_at": "now"}))
    with pytest.raises(SystemExit):
        wr.main([])
    text = (env["logs"] / "refresh.log").read_text(encoding="utf-8")
    assert "Another refresh is running" in text


def test_a_lock_that_cannot_be_created_exits_2(fake_run, env, monkeypatch, caplog):
    not_a_folder = env["logs"].parent / "not_a_folder"
    not_a_folder.write_text("a file where the logs folder should be")
    monkeypatch.setattr(wr, "LOCK_PATH", not_a_folder / "refresh.lock")
    with pytest.raises(SystemExit) as exit_info:
        wr.main([])
    assert exit_info.value.code == 2
    assert "Could not create the lock" in caplog.text
    assert env["warehouse"].read_bytes() == OLD


def test_no_publish_with_a_failing_step(fake_run, env):
    out = fake_run("dbt_build", argv=("--no-publish",))
    assert out["exit"] == 1
    assert out["run"]["dry_run"] is True
    assert out["run"]["ok"] is False
    assert "swap" not in [s["step"] for s in out["run"]["steps"]]
    assert env["warehouse"].read_bytes() == OLD
    assert not env["copy"].exists()
    assert out["git"] == []
    assert len(out["lines"]) == 1


def test_an_old_stale_wal_is_never_put_beside_the_warehouse(fake_run, env, monkeypatch):
    # a previous run moved a WAL aside but could not delete it
    stale = wr.wal_path(env["warehouse"])
    aside = stale.with_name(stale.name + ".stale")
    aside.write_bytes(b"wal of a file that is gone")
    _replace_failing(monkeypatch, None)
    out = fake_run(after=CLEAN_CLOSE)
    assert out["exit"] == 1
    assert not stale.exists()


def test_a_failed_taskkill_is_logged(monkeypatch, caplog):
    monkeypatch.setattr(wr.sys, "platform", "win32")
    monkeypatch.setattr(
        wr.subprocess,
        "run",
        lambda cmd, **k: subprocess.CompletedProcess(cmd, 128, "", "ERROR: process not found"),
    )
    wr.kill_tree(_Proc())  # type: ignore[arg-type]
    assert "taskkill exited 128: ERROR: process not found" in caplog.text


def test_an_interrupted_step_is_killed_not_left_running(monkeypatch, tmp_path):
    killed = []

    class InterruptedPopen(_Proc):
        def __init__(self, cmd, **kwargs):
            super().__init__()

        def communicate(self, timeout=None):
            raise KeyboardInterrupt

    monkeypatch.setattr(wr.subprocess, "Popen", InterruptedPopen)
    monkeypatch.setattr(wr, "kill_tree", lambda proc: killed.append(proc.pid))
    with pytest.raises(KeyboardInterrupt):
        wr.run_step("ingest", ["x"], warehouse=tmp_path / "w.duckdb", log_dir=tmp_path / "logs")
    assert killed == [4242]
