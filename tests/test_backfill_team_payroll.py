"""scripts/backfill_team_payroll.py: every season is attempted, and the run
exits non-zero when any of them came back incomplete. write_season and the
warehouse-derived team lists are stubbed, so nothing is fetched or read."""

import logging

import pytest

from scripts import backfill_team_payroll


@pytest.fixture
def seasons(monkeypatch):
    by_season = {"1990-91": ["BOS"], "1991-92": ["BOS"], "1992-93": ["BOS"]}
    monkeypatch.setattr(backfill_team_payroll, "seasons_and_teams", lambda: by_season)
    monkeypatch.setattr("sys.argv", ["backfill_team_payroll.py"])
    return by_season


def test_exits_non_zero_after_all_seasons_when_one_was_incomplete(monkeypatch, seasons, caplog):
    attempted = []

    def fake_write(season, teams, force=False):
        attempted.append(season)
        return season != "1991-92"

    monkeypatch.setattr(backfill_team_payroll, "write_season", fake_write)
    with caplog.at_level(logging.ERROR), pytest.raises(SystemExit) as exc:
        backfill_team_payroll.main()

    assert exc.value.code == 1
    assert attempted == list(seasons), "a failed season must not stop the later ones"
    assert "1991-92" in caplog.text
    assert "1990-91" not in caplog.text


def test_exits_zero_when_every_season_completed(monkeypatch, seasons):
    monkeypatch.setattr(backfill_team_payroll, "write_season", lambda *a, **k: True)
    backfill_team_payroll.main()
