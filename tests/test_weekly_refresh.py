"""The weekly refresh's step logic: which failures stop the run and which
are recorded and carried past. No subprocess runs here - run_step, git and
the payroll step list are faked, and the log and version files go to a temp
folder."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import weekly_refresh as wr  # noqa: E402


@pytest.fixture
def fake_run(tmp_path, monkeypatch):
    """Run main() with the named steps failing; returns what happened."""

    def go(*failing: str) -> dict:
        ran: list[str] = []
        commits: list[str] = []

        def run_step(name, cmd, cwd=None):
            ran.append(name)
            ok = name not in failing
            entry = {"step": name, "ok": ok, "seconds": 0.0}
            if not ok:
                entry["error"] = "boom"
            return entry

        def git(*args):
            if args[0] == "commit":
                commits.append(args[2])
            # "diff --cached --quiet" exits 1 when something is staged
            return subprocess.CompletedProcess(args, 1 if args[0] == "diff" else 0)

        (tmp_path / "warehouse").mkdir(exist_ok=True)
        log = tmp_path / "logs" / "refresh_runs.jsonl"
        monkeypatch.setattr(wr, "run_step", run_step)
        monkeypatch.setattr(wr, "git", git)
        monkeypatch.setattr(
            wr,
            "payroll_steps",
            lambda: [("payroll", ["payroll"], None), ("load_payroll", ["load"], None)],
        )
        monkeypatch.setattr(wr, "PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(wr, "LOG_PATH", log)
        with pytest.raises(SystemExit) as exit_info:
            wr.main()
        run = json.loads(log.read_text().splitlines()[-1])
        return {"ran": ran, "commits": commits, "run": run, "exit": exit_info.value.code}

    return go


def test_a_clean_run_publishes_and_commits_ok(fake_run):
    out = fake_run()
    assert out["exit"] == 0
    assert out["run"]["ok"] is True
    assert out["run"]["player_impact_ok"] is True
    assert out["run"]["payroll_ok"] is True
    assert "publish_release" in out["ran"]
    assert out["commits"][0].startswith("Weekly refresh: ok ")


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
    out = fake_run("dbt_run")
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
