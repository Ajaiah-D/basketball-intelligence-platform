"""Tests for the Basketball-Reference team payroll scraper."""

from pathlib import Path

import pandas as pd
import pytest

from ingestion import team_payroll_ingest
from ingestion.team_payroll_ingest import (
    bbref_code,
    parse_salary_table,
    season_end_year,
    team_season_payroll,
)

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


def _fake_pages(pages: dict[str, str], monkeypatch):
    """Serve canned HTML per bbref team code, so the tests below never hit the network."""
    def fake_fetch(team_code, season):
        return pages[team_code]
    monkeypatch.setattr(team_payroll_ingest, "fetch_team_season_html", fake_fetch)


def test_team_season_payroll_reports_row_count_alongside_total(monkeypatch):
    html = FIXTURE.read_text(encoding="utf-8")
    _fake_pages({"BOS": html}, monkeypatch)
    result = team_season_payroll("BOS", "2009-10")
    assert result["team_payroll"] == 83552174
    assert result["player_count"] == 14


def test_team_season_payroll_with_no_salary_table_is_none_not_zero(monkeypatch):
    # None, never 0: a real team's payroll is never actually zero, so 0 would be
    # indistinguishable from a genuine value once it reaches a chart.
    _fake_pages({"BOS": "<html><body>no table here</body></html>"}, monkeypatch)
    result = team_season_payroll("BOS", "1986-87")
    assert result["team_payroll"] is None
    assert result["player_count"] == 0


def test_ingest_season_writes_a_row_for_a_team_with_no_data(monkeypatch):
    # The 1986-87/1989-90 source gap: a skipped team-season vanishes from the
    # parquet entirely, and a completeness flag can't fire for a row that
    # doesn't exist. Every requested team must produce a row.
    html = FIXTURE.read_text(encoding="utf-8")
    _fake_pages({"BOS": html, "DAL": "<html>nothing</html>"}, monkeypatch)
    df = team_payroll_ingest.ingest_season("1986-87", ["BOS", "DAL"])

    assert len(df) == 2
    assert sorted(df["team_abbreviation"]) == ["BOS", "DAL"]
    dal = df[df["team_abbreviation"] == "DAL"].iloc[0]
    assert dal["team_payroll"] is None or pd.isna(dal["team_payroll"])
    assert dal["player_count"] == 0
    bos = df[df["team_abbreviation"] == "BOS"].iloc[0]
    assert bos["team_payroll"] == 83552174
    assert bos["player_count"] == 14


def test_ingest_season_columns_include_player_count(monkeypatch):
    _fake_pages({"BOS": FIXTURE.read_text(encoding="utf-8")}, monkeypatch)
    df = team_payroll_ingest.ingest_season("2009-10", ["BOS"])
    assert list(df.columns) == ["season", "team_abbreviation", "team_payroll", "player_count"]


def test_write_season_parquet_round_trips_player_count(tmp_path, monkeypatch):
    _fake_pages({"BOS": FIXTURE.read_text(encoding="utf-8"), "DAL": "<html>x</html>"}, monkeypatch)
    monkeypatch.setattr(team_payroll_ingest, "RAW_DIR", tmp_path)
    team_payroll_ingest.write_season("2009-10", ["BOS", "DAL"])

    df = pd.read_parquet(tmp_path / "2009-10.parquet")
    assert list(df.columns) == ["season", "team_abbreviation", "team_payroll", "player_count"]
    assert len(df) == 2
    assert df["player_count"].notna().all()
    assert set(df["player_count"]) == {0, 14}
