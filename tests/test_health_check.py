"""health_check reads the last scheduled run from logs/refresh_runs.jsonl,
skipping the git_push lines and --no-publish dry runs written after it."""

import json
import sys
from pathlib import Path

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
