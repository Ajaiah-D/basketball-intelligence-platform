"""health_check reads the last scheduled run from logs/refresh_runs.jsonl,
skipping the git_push lines and --no-publish dry runs written after it."""

import json
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import health_check

RUN = {"run_at": "2026-10-20T10:00:00+00:00", "steps": [], "ok": True}


def test_the_last_run_skips_push_lines_and_dry_runs():
    lines = [
        json.dumps({**RUN, "run_at": "2026-10-13T10:00:00+00:00"}),
        json.dumps(RUN),
        json.dumps({"run_at": RUN["run_at"], "step": "git_push", "ok": False, "error": "x"}),
        json.dumps({**RUN, "run_at": "2026-10-21T09:00:00+00:00", "dry_run": True}),
    ]
    run, push = health_check.last_scheduled_run(lines)
    assert run == RUN
    assert push is not None and push["ok"] is False


def test_the_last_run_without_a_push_line():
    run, push = health_check.last_scheduled_run([json.dumps(RUN)])
    assert run == RUN
    assert push is None


def test_no_scheduled_run_at_all():
    dry = json.dumps({**RUN, "dry_run": True})
    assert health_check.last_scheduled_run([dry]) == (None, None)


def test_check_last_run_notes_a_failed_push_and_counts_only_scheduled_runs(
    tmp_path, monkeypatch, capsys
):
    log = tmp_path / "logs" / "refresh_runs.jsonl"
    log.parent.mkdir()
    recent = health_check.datetime.now(health_check.UTC).isoformat(timespec="seconds")
    run = {**RUN, "run_at": recent}
    log.write_text(
        "\n".join(
            [
                json.dumps({**RUN, "run_at": "2026-10-13T10:00:00+00:00"}),
                json.dumps(run),
                json.dumps(
                    {"run_at": recent, "step": "git_push", "ok": False, "error": "rejected"}
                ),
                json.dumps({**run, "dry_run": True}),
            ]
        )
        + "\n"
    )
    monkeypatch.setattr(health_check, "LOG_PATH", log)
    monkeypatch.setattr(health_check, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(health_check, "CHECKS_FAILED", [])
    health_check.check_last_run()
    printed = capsys.readouterr().out
    assert "NOTE git push after that run failed: rejected" in printed
    assert "(2 scheduled run(s) recorded" in printed
    assert health_check.CHECKS_FAILED == []


def _check_last_run(tmp_path, monkeypatch, capsys, run: dict) -> str:
    """check_last_run() against a log holding only `run`, dated now; what it printed."""
    log = tmp_path / "logs" / "refresh_runs.jsonl"
    log.parent.mkdir(parents=True)
    recent = health_check.datetime.now(health_check.UTC).isoformat(timespec="seconds")
    log.write_text(json.dumps({**run, "run_at": recent}) + "\n")
    monkeypatch.setattr(health_check, "LOG_PATH", log)
    monkeypatch.setattr(health_check, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(health_check, "CHECKS_FAILED", [])
    health_check.check_last_run()
    assert health_check.CHECKS_FAILED == [], "a warning is a note, not a failed check"
    return capsys.readouterr().out


def test_check_last_run_notes_dbt_warnings(tmp_path, monkeypatch, capsys):
    run = {**RUN, "dbt_warnings": 2, "dbt_warning_tests": ["assert_a", "assert_b"]}
    printed = _check_last_run(tmp_path, monkeypatch, capsys, run)
    assert "NOTE dbt finished that run with 2 warning(s): assert_a, assert_b" in printed


def test_check_last_run_is_quiet_without_dbt_warnings(tmp_path, monkeypatch, capsys):
    zero = _check_last_run(tmp_path / "zero", monkeypatch, capsys, {**RUN, "dbt_warnings": 0})
    older = _check_last_run(tmp_path / "older", monkeypatch, capsys, RUN)  # no key at all
    assert "dbt finished" not in zero + older


@pytest.mark.parametrize(
    ("day", "offseason"),
    [
        (date(2026, 4, 20), False),  # the last days of the regular season
        (date(2026, 4, 21), True),
        (date(2026, 7, 1), True),
        (date(2026, 10, 1), True),  # the new season is current, no games yet
        (date(2026, 10, 14), True),
        (date(2026, 10, 15), False),  # the checks expect games again
        (date(2027, 1, 15), False),
    ],
)
def test_offseason_bounds(day, offseason):
    assert health_check.in_offseason(day) is offseason
