"""health_check reads the last scheduled run from logs/refresh_runs.jsonl,
skipping the git_push lines and --no-publish dry runs written after it."""

import json
import sys
from datetime import date
from pathlib import Path

import duckdb
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


@pytest.fixture
def schedule_db(tmp_path):
    """A warehouse whose 2026-27 schedule opens on October 21, after a
    preseason game that must not count as opening night."""
    path = tmp_path / "schedule.duckdb"
    con = duckdb.connect(str(path))
    con.execute("create schema main_staging")
    con.execute(
        "create table main_staging.stg_schedule "
        "(season varchar, game_date date, is_regular_season boolean)"
    )
    con.execute(
        "insert into main_staging.stg_schedule values "
        "('2026-27', '2026-10-05', false), "
        "('2026-27', '2026-10-21', true), "
        "('2026-27', '2026-10-22', true), "
        "('2027-28', '2027-10-19', false)"
    )
    con.close()
    return path


@pytest.mark.parametrize(
    ("day", "offseason"),
    [
        (date(2026, 4, 20), False),  # the last days of the regular season
        (date(2026, 4, 21), True),
        (date(2026, 7, 1), True),
        (date(2026, 10, 1), True),  # the new season is current, no games yet
        (date(2026, 10, 6), True),  # a preseason game is not opening night
        (date(2026, 10, 15), True),  # no longer cut off mid-October
        (date(2026, 10, 20), True),
        # Opening night plus LATEST_GAME_MAX_AGE_DAYS (7) of grace for the
        # weekly refresh to load the first games: offseason while
        # today < opening night + 7 days.
        (date(2026, 10, 21), True),  # opening night
        (date(2026, 10, 27), True),  # opening night + 6
        (date(2026, 10, 28), False),  # opening night + 7: the checks expect games
        (date(2026, 12, 1), False),
        (date(2027, 1, 15), False),
    ],
)
def test_offseason_ends_at_the_scheduled_opening_night(schedule_db, day, offseason):
    assert health_check.in_offseason(day, schedule_db) is offseason


def test_opening_night_comes_from_the_regular_season_schedule(schedule_db):
    assert health_check.opening_night(date(2026, 7, 1), schedule_db) == date(2026, 10, 21)
    assert health_check.opening_night(date(2026, 11, 1), schedule_db) == date(2026, 10, 21)


@pytest.mark.parametrize(
    ("day", "offseason"),
    [
        (date(2027, 4, 21), True),
        (date(2027, 10, 31), True),  # OFFSEASON_FALLBACK_END, inside the grace week
        (date(2027, 11, 6), True),  # fallback + 6
        (date(2027, 11, 7), False),  # fallback + 7
    ],
)
def test_offseason_falls_back_when_the_schedule_lacks_the_season(schedule_db, day, offseason):
    # 2027-28 has only a preseason game in this schedule.
    assert health_check.in_offseason(day, schedule_db) is offseason


def test_offseason_falls_back_without_a_readable_schedule(tmp_path):
    missing = tmp_path / "missing.duckdb"
    empty = tmp_path / "empty.duckdb"
    duckdb.connect(str(empty)).close()  # a warehouse with no stg_schedule
    for path in (missing, empty):
        assert health_check.opening_night(date(2026, 7, 1), path) == date(2026, 10, 31)
        assert health_check.in_offseason(date(2026, 11, 6), path) is True
        assert health_check.in_offseason(date(2026, 11, 7), path) is False
    assert not missing.exists()  # a read-only probe never creates the file


@pytest.mark.parametrize(
    ("day", "phrase"),
    [
        (date(2026, 7, 1), None),
        (date(2026, 10, 20), None),  # the eve of opening night: still the offseason
        (date(2026, 10, 21), "the season just started (opening night 2026-10-21)"),
        (date(2026, 10, 27), "the season just started (opening night 2026-10-21)"),
        (date(2026, 10, 28), None),  # grace over: in season, no qualifier
        (date(2027, 1, 15), None),
    ],
)
def test_the_grace_week_is_called_the_season_starting(schedule_db, day, phrase):
    assert health_check.season_just_started(day, schedule_db) == phrase


def test_the_grace_week_on_the_fallback_says_the_date_is_assumed(schedule_db):
    # 2027-28 has only a preseason game, so opening night is the fallback.
    assert health_check.season_just_started(date(2027, 10, 30), schedule_db) is None
    assert health_check.season_just_started(date(2027, 10, 31), schedule_db) == (
        "the season just started (opening night 2027-10-31, "
        "assumed: the schedule doesn't have it yet)"
    )


@pytest.fixture
def grace_week(schedule_db, monkeypatch):
    """Today is 2026-10-23, two days after schedule_db's opening night, with
    the checks pointed at a warehouse whose latest game is that night."""
    con = duckdb.connect(str(schedule_db))
    con.execute("create table main_staging.stg_team_game_logs (game_date date)")
    con.execute("insert into main_staging.stg_team_game_logs values ('2026-10-21')")
    con.close()

    class Today(date):
        @classmethod
        def today(cls):
            return cls(2026, 10, 23)

    monkeypatch.setattr(health_check, "date", Today)
    monkeypatch.setattr(health_check, "DB_PATH", schedule_db)
    monkeypatch.setattr(health_check, "CHECKS_FAILED", [])
    return schedule_db


def test_freshness_in_the_grace_week_says_the_season_just_started(grace_week, capsys):
    health_check.check_freshness()
    printed = capsys.readouterr().out
    assert "the season just started (opening night 2026-10-21)" in printed
    assert "offseason" not in printed
    assert health_check.CHECKS_FAILED == []


def test_the_last_run_in_the_grace_week_says_the_season_just_started(
    grace_week, tmp_path, monkeypatch, capsys
):
    printed = _check_last_run(tmp_path, monkeypatch, capsys, RUN)
    assert "succeeded; the season just started (opening night 2026-10-21)" in printed
    assert "idle until the season starts" not in printed


def test_a_failed_non_fatal_step_is_noted_as_carried_over(tmp_path, monkeypatch, capsys):
    steps = [{"step": "payroll", "ok": False}, {"step": "player_impact", "ok": True}]
    printed = _check_last_run(tmp_path, monkeypatch, capsys, {**RUN, "steps": steps})
    assert "NOTE step 'payroll' failed but did not block the run; the warehouse is carrying" in (
        printed
    )


def test_a_failed_drop_snapshot_is_noted_with_its_own_error(tmp_path, monkeypatch, capsys):
    error = "could not delete history.csv.pre-run: locked; overwrote it with the published history"
    steps = [{"step": "drop_snapshot", "ok": False, "error": error}]
    printed = _check_last_run(tmp_path, monkeypatch, capsys, {**RUN, "steps": steps})
    assert f"NOTE step 'drop_snapshot' failed after the run published: {error}" in printed
    assert "last week's data" not in printed
