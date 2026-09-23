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
    ("PHX", "1984-85", "PHO"),   # Suns, permanent mismatch (not era-limited)
    ("PHX", "2025-26", "PHO"),   # Suns, still PHO in the modern era too
    ("WAS", "1984-85", "WSB"),   # Bullets, pre-1997-98 rename
    ("WAS", "1996-97", "WSB"),   # last season still under "WSB"
    ("WAS", "1997-98", "WAS"),   # Wizards rename season, bbref code changes too
    ("WAS", "2020-21", "WAS"),   # modern code, passes through unchanged
    ("BKN", "2012-13", "BRK"),   # Nets, permanent mismatch since the Brooklyn move
    ("BKN", "2025-26", "BRK"),   # Nets, still BRK in the modern era too
    ("CHA", "1984-85", "CHA"),   # unaffected pre-expansion year, passes through unchanged
    ("CHA", "2013-14", "CHA"),   # last season still under "CHA" (Bobcats era)
    ("CHA", "2014-15", "CHO"),   # Hornets rename season, bbref code changes too
    ("CHA", "2020-21", "CHO"),   # modern code stays CHO
])
def test_bbref_code_maps_legacy_codes(nba_code, season, expected):
    assert bbref_code(nba_code, season) == expected
