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
HISTORY = b"prediction_id,game_id\nold,0022600001\n"
APPENDED = b"new,0022600002\n"


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
    history = tmp_path / "data" / "predictions" / "history.csv"
    history.parent.mkdir(parents=True)
    history.write_bytes(HISTORY)
    monkeypatch.setattr(wr, "HISTORY_PATH", history)
    monkeypatch.setattr(wr, "LAST_UPDATED_PATH", tmp_path / "data" / "last_updated.json")
    # The swap tests fake os.replace to lock the warehouse; the history's
    # writes would hit the same fake. Their atomicity is core.io's, tested
    # in test_core_io.py, so here they are plain writes.
    monkeypatch.setattr(wr, "atomic_write_bytes", lambda data, path: path.write_bytes(data))
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
        "history": history,
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


# What dbt build writes to dbt_build.log when a test warns, colour codes
# and all (trimmed from a real run).
DBT_WARN_OUTPUT = (
    "\x1b[0m11:37:18  1 of 3 START test assert_marts_not_empty ..... [RUN]\n"
    "\x1b[0m11:37:18  2 of 3 WARN 2 assert_player_season_matches_game_logs ..... "
    "[\x1b[33mWARN 2\x1b[0m in 0.03s]\n"
    "\x1b[0m11:37:18  1 of 3 PASS assert_marts_not_empty ..... [\x1b[32mPASS\x1b[0m in 0.04s]\n"
    "\x1b[0m11:37:18  [\x1b[33mWARNING\x1b[0m]: in test assert_player_season_matches_game_logs\n"
    "\x1b[0m11:37:18  Done. PASS=2 WARN=1 ERROR=0 SKIP=0 NO-OP=0 REUSED=0 TOTAL=3\n"
)


def test_dbt_warnings_reads_the_summary_and_the_warning_tests():
    assert wr.dbt_warnings(DBT_WARN_OUTPUT) == (1, ["assert_player_season_matches_game_logs"])
    clean = "Done. PASS=131 WARN=0 ERROR=0 SKIP=0 NO-OP=0 REUSED=0 TOTAL=131\n"
    assert wr.dbt_warnings(clean) == (0, [])
    assert wr.dbt_warnings("Compilation Error in model foo\n") is None


def test_dbt_warnings_go_on_the_run_line(fake_run):
    out = fake_run(output={"dbt_build": DBT_WARN_OUTPUT})
    assert out["exit"] == 0, "a warning does not fail the run"
    assert out["run"]["dbt_warnings"] == 1
    assert out["run"]["dbt_warning_tests"] == ["assert_player_season_matches_game_logs"]


def test_a_clean_dbt_build_records_zero_warnings(fake_run):
    out = fake_run(output={"dbt_build": "Done. PASS=131 WARN=0 ERROR=0 SKIP=0 TOTAL=131\n"})
    assert out["run"]["dbt_warnings"] == 0
    assert "dbt_warning_tests" not in out["run"]


def test_a_failed_dbt_build_still_records_its_warnings(fake_run):
    # A test that errors stops the build but dbt still prints its summary;
    # the warnings in it are recorded and the run fails exactly as before.
    output = (
        "1 of 3 WARN 2 assert_player_season_matches_game_logs ..... [WARN 2 in 0.1s]\n"
        "2 of 3 FAIL 1 assert_marts_not_empty ..... [FAIL 1 in 0.1s]\n"
        "Done. PASS=1 WARN=1 ERROR=1 SKIP=0 NO-OP=0 REUSED=0 TOTAL=3\n"
    )
    out = fake_run("dbt_build", output={"dbt_build": output})
    assert out["exit"] != 0
    assert out["run"]["ok"] is False
    (dbt,) = [s for s in out["run"]["steps"] if s["step"] == "dbt_build"]
    assert dbt["ok"] is False
    assert "player_impact" not in out["ran"]
    assert out["run"]["dbt_warnings"] == 1
    assert out["run"]["dbt_warning_tests"] == ["assert_player_season_matches_game_logs"]


def test_a_dbt_log_without_a_summary_records_nothing(fake_run):
    out = fake_run("dbt_build", output={"dbt_build": "Compilation Error in model foo\n"})
    assert "dbt_warnings" not in out["run"]


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


@pytest.fixture
def real_repo(env, tmp_path):
    """The temp folder as a real git repo holding the refresh's three files
    and one unrelated file, all committed. Returns a git runner for it."""

    def git(*args: str) -> str:
        done = subprocess.run(
            ["git", *args], cwd=tmp_path, capture_output=True, text=True, check=True
        )
        return done.stdout

    git("init", "-q")
    git("config", "user.name", "Refresh Test")
    git("config", "user.email", "refresh@example.invalid")
    git("config", "commit.gpgsign", "false")
    (tmp_path / "data" / "last_updated.json").write_text("{}\n")
    env["logs"].mkdir()
    wr.LOG_PATH.write_text("")
    (tmp_path / "notes.txt").write_text("draft\n")
    git("add", "-A")
    git("commit", "-q", "-m", "start")
    # Someone's half-done edit, staged in the same checkout.
    (tmp_path / "notes.txt").write_text("half-done edit\n")
    git("add", "notes.txt")
    return git


RUN = {
    "run_at": "2026-10-27T10:00:00+00:00",
    "ok": True,
    "payroll_ok": True,
    "player_impact_ok": True,
}


def test_the_commit_takes_only_the_refresh_s_own_files(env, tmp_path, real_repo):
    (tmp_path / "data" / "last_updated.json").write_text('{"updated_at": "now"}\n')
    wr.LOG_PATH.write_text('{"run_at": "2026-10-27T10:00:00+00:00"}\n')
    env["history"].write_bytes(HISTORY + APPENDED)
    entry = wr.commit_and_push(RUN, with_history=True)
    assert "git push failed" in entry["error"], "no remote: only the push fails"
    committed = real_repo("show", "--name-only", "--format=", "HEAD").split()
    assert sorted(committed) == [
        "data/last_updated.json",
        "data/predictions/history.csv",
        "logs/refresh_runs.jsonl",
    ]
    assert real_repo("diff", "--cached", "--name-only").split() == ["notes.txt"]


def test_nothing_of_its_own_to_commit_commits_nothing(real_repo):
    head = real_repo("rev-parse", "HEAD")
    entry = wr.commit_and_push(RUN, with_history=True)
    assert entry["ok"] is True
    assert real_repo("rev-parse", "HEAD") == head
    assert real_repo("diff", "--cached", "--name-only").split() == ["notes.txt"]


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


def _predict_appends(env):
    """An `after` hook: the predict step appending a row to the history."""

    def append(_warehouse: Path) -> None:
        with env["history"].open("ab") as f:
            f.write(APPENDED)

    return {"predict": append}


def _added(out) -> tuple[str, ...]:
    return next(args for args in out["git"] if args[0] == "add")


def test_a_published_run_keeps_and_commits_its_predictions(fake_run, env):
    out = fake_run(after=_predict_appends(env))
    assert out["run"]["ok"] is True
    assert env["history"].read_bytes() == HISTORY + APPENDED
    assert "data/predictions/history.csv" in _added(out)


# The history holds only predictions from runs that were published, the same
# all-or-nothing rule as the warehouse copy.
@pytest.mark.parametrize("failing", ["score_predictions", "write_metadata", "publish_release"])
def test_a_run_that_is_not_published_discards_its_predictions(fake_run, env, failing):
    out = fake_run(failing, after=_predict_appends(env))
    assert out["run"]["ok"] is False
    assert env["history"].read_bytes() == HISTORY
    assert "data/predictions/history.csv" not in _added(out)
    refresh_log = (env["logs"].parent / out["run"]["log"]).read_text()
    assert "discarded" in refresh_log


def test_a_failed_swap_discards_the_predictions_too(fake_run, env, monkeypatch):
    monkeypatch.setattr(wr, "swap", lambda copy, warehouse: "warehouse is locked")
    out = fake_run(after=_predict_appends(env))
    assert out["run"]["ok"] is False
    assert env["history"].read_bytes() == HISTORY
    assert "data/predictions/history.csv" not in _added(out)


def test_a_failed_restore_is_recorded_and_the_snapshot_kept(fake_run, env, monkeypatch):
    def full_disk(snapshot):
        raise OSError("disk full")

    monkeypatch.setattr(wr, "restore_history", full_disk)
    out = fake_run("score_predictions", after=_predict_appends(env))
    (restore,) = [s for s in out["run"]["steps"] if s["step"] == "restore_history"]
    assert restore["ok"] is False
    assert "disk full" in restore["error"]
    assert "data/predictions/history.csv" not in _added(out)
    # still there for the next run to roll back
    assert wr.snapshot_path().read_bytes() == b"present\n" + HISTORY


def test_the_snapshot_is_gone_after_a_published_run(fake_run, env):
    fake_run(after=_predict_appends(env))
    assert not wr.snapshot_path().exists()


def test_the_snapshot_is_gone_after_a_rolled_back_run(fake_run, env):
    fake_run("score_predictions", after=_predict_appends(env))
    assert not wr.snapshot_path().exists()


def test_a_snapshot_is_written_before_any_step_runs(fake_run, env):
    seen: list[bytes] = []
    fake_run(after={"ingest": lambda _w: seen.append(wr.snapshot_path().read_bytes())})
    assert seen == [b"present\n" + HISTORY]


def test_ctrl_c_after_predict_rolls_the_history_back(fake_run, env, monkeypatch):
    committed: list[dict] = []
    monkeypatch.setattr(wr, "commit_and_push", lambda run, **kw: committed.append(kw) or {})

    def interrupt(_warehouse: Path) -> None:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        fake_run(after={**_predict_appends(env), "score_predictions": interrupt})
    assert env["history"].read_bytes() == HISTORY
    assert not wr.snapshot_path().exists()
    assert committed == []


def test_a_version_upload_failure_keeps_the_released_predictions(fake_run, env):
    # The warehouse asset - and the predictions in it - is already on the
    # release; only the marker failed. The run fails, the rows stay.
    out = fake_run("publish_version", after=_predict_appends(env))
    assert out["run"]["ok"] is False
    assert env["history"].read_bytes() == HISTORY + APPENDED
    assert "data/predictions/history.csv" in _added(out)
    assert not wr.snapshot_path().exists()


@pytest.mark.parametrize("argv", [(), ("--no-publish",)])
def test_a_killed_run_s_snapshot_is_restored_first(fake_run, env, argv):
    # A hard kill skips every finally: the next run, of either kind, undoes it.
    env["history"].write_bytes(HISTORY + APPENDED)
    wr.snapshot_path().write_bytes(b"present\n" + HISTORY)
    seen: list[bytes] = []
    out = fake_run(argv=argv, after={"ingest": lambda _w: seen.append(env["history"].read_bytes())})
    assert seen == [HISTORY]
    assert env["history"].read_bytes() == HISTORY
    refresh_log = (env["logs"].parent / out["run"]["log"]).read_text()
    assert "previous run was interrupted; discarded its unpublished predictions" in refresh_log
    assert not wr.snapshot_path().exists()


def test_a_snapshot_that_cannot_be_deleted_after_publishing_is_neutralised(
    fake_run, env, monkeypatch
):
    unlink = Path.unlink

    def locked_snapshot(self, *args, **kwargs):
        if self == wr.snapshot_path():
            raise PermissionError(32, "in use by a scanner")
        return unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", locked_snapshot)
    out = fake_run(after=_predict_appends(env))
    assert out["run"]["ok"] is True
    (drop,) = [s for s in out["run"]["steps"] if s["step"] == "drop_snapshot"]
    assert drop["ok"] is False
    assert "in use by a scanner" in drop["error"]
    published = env["history"].read_bytes()
    assert published == HISTORY + APPENDED

    # The lock is gone by the next run, which finds the snapshot left over:
    # rolling back to it must not take the published predictions out.
    monkeypatch.setattr(Path, "unlink", unlink)
    fake_run(argv=("--no-publish",))
    assert env["history"].read_bytes() == published
    assert not wr.snapshot_path().exists()


def test_a_killed_run_that_created_the_history_leaves_none(fake_run, env):
    wr.snapshot_path().write_bytes(b"absent\n")
    fake_run(argv=("--no-publish",))
    assert not env["history"].exists()
    assert not wr.snapshot_path().exists()


def test_an_unreadable_snapshot_stops_the_run_and_is_kept(fake_run, env):
    wr.snapshot_path().write_bytes(b"garbage")
    out = fake_run()
    assert out["exit"] == 1
    assert "ingest" not in out["ran"]
    assert wr.snapshot_path().read_bytes() == b"garbage"
    assert "data/predictions/history.csv" not in _added(out)


def test_a_history_first_created_by_a_failed_run_is_removed(fake_run, env):
    env["history"].unlink()

    def create(_warehouse: Path) -> None:
        env["history"].write_bytes(HISTORY)

    fake_run("score_predictions", after={"predict": create})
    assert not env["history"].exists()


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
