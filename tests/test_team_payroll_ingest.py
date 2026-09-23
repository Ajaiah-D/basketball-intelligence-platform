"""Tests for the Basketball-Reference team payroll scraper."""

from pathlib import Path

import pytest

from ingestion.team_payroll_ingest import bbref_code, parse_salary_table, season_end_year

FIXTURE = Path(__file__).parent.parent / "data" / "fixtures" / "bbref_team_salary_page.html"


def test_parse_salary_table_extracts_every_player_row():
    html = FIXTURE.read_text(encoding="utf-8")
    rows = parse_salary_table(html)
    assert len(rows) == 14  # the 2009-10 Celtics fixture has 14 rostered players with salaries
    assert rows[0]["player"] == "Paul Pierce"
    assert rows[0]["salary_usd"] == 19795712
    assert rows[1]["player"] == "Ray Allen"
    assert rows[1]["salary_usd"] == 18776860


def test_parse_salary_table_total_matches_known_payroll():
    html = FIXTURE.read_text(encoding="utf-8")
    rows = parse_salary_table(html)
    total = sum(r["salary_usd"] for r in rows)
    assert total == 83552174  # verified by hand-summing the fixture's 14 rows


def test_parse_salary_table_empty_page_returns_empty_list():
    assert parse_salary_table("<html><body>no table here</body></html>") == []


@pytest.mark.parametrize("season,expected", [
    ("1984-85", 1985),
    ("1999-00", 2000),
    ("2009-10", 2010),
    ("2026-27", 2027),
])
def test_season_end_year(season, expected):
    assert season_end_year(season) == expected


@pytest.mark.parametrize("nba_code,season,expected", [
    ("SAN", "1990-91", "SAS"),   # Spurs, pre-1996-97 legacy code
    ("GOS", "1990-91", "GSW"),   # Warriors, pre-1996-97 legacy code
    ("UTH", "1990-91", "UTA"),   # Jazz, pre-1996-97 legacy code
    ("PHL", "1990-91", "PHI"),   # 76ers, pre-1996-97 legacy code
    ("BOS", "1990-91", "BOS"),   # unaffected code, passes through unchanged
    ("SAS", "2020-21", "SAS"),   # modern code, passes through unchanged
])
def test_bbref_code_maps_legacy_codes(nba_code, season, expected):
    assert bbref_code(nba_code, season) == expected
