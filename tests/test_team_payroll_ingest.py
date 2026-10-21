"""Tests for the Basketball-Reference team payroll scraper. Nothing here
reaches the site: requests.get or the page fetch is always faked."""

import logging
from pathlib import Path

import pandas as pd
import pytest
import requests

from core import io as core_io
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
    assert rows[0]["bbref_player_id"] == "piercpa01"
    assert rows[1]["bbref_player_id"] == "allenra02"


def test_parse_salary_table_unescapes_player_names():
    html = (
        '<table id="salaries2"><tr>'
        '<td class="left" data-append-csv="oneilsh01" data-stat="player" >'
        '<a href="/players/o/oneilsh01.html">Shaquille O&#x27;Neal</a></td>'
        '<td class="right" data-stat="salary" csk="17142000" >$17,142,000</td>'
        "</tr></table>"
    )
    rows = parse_salary_table(html)
    assert rows == [
        {"bbref_player_id": "oneilsh01", "player": "Shaquille O'Neal", "salary_usd": 17142000}
    ]


def test_parse_salary_table_total_matches_known_payroll():
    html = FIXTURE.read_text(encoding="utf-8")
    rows = parse_salary_table(html)
    total = sum(r["salary_usd"] for r in rows)
    assert total == 83552174  # verified by hand-summing the fixture's 14 rows


def test_parse_salary_table_empty_page_returns_empty_list():
    assert parse_salary_table("<html><body>no table here</body></html>") == []


@pytest.mark.parametrize(
    "season,expected",
    [
        ("1984-85", 1985),
        ("1999-00", 2000),
        ("2009-10", 2010),
        ("2026-27", 2027),
    ],
)
def test_season_end_year(season, expected):
    assert season_end_year(season) == expected


@pytest.mark.parametrize(
    "nba_code,season,expected",
    [
        ("SAN", "1990-91", "SAS"),  # Spurs, pre-1996-97 legacy code
        ("GOS", "1990-91", "GSW"),  # Warriors, pre-1996-97 legacy code
        ("UTH", "1990-91", "UTA"),  # Jazz, pre-1996-97 legacy code
        ("PHL", "1990-91", "PHI"),  # 76ers, pre-1996-97 legacy code
        ("BOS", "1990-91", "BOS"),  # unaffected code, passes through unchanged
        ("SAS", "2020-21", "SAS"),  # modern code, passes through unchanged
        ("PHX", "1984-85", "PHO"),  # Suns, permanent mismatch (not era-limited)
        ("PHX", "2025-26", "PHO"),  # Suns, still PHO in the modern era too
        ("WAS", "1984-85", "WSB"),  # Bullets, pre-1997-98 rename
        ("WAS", "1996-97", "WSB"),  # last season still under "WSB"
        ("WAS", "1997-98", "WAS"),  # Wizards rename season, bbref code changes too
        ("WAS", "2020-21", "WAS"),  # modern code, passes through unchanged
        ("BKN", "2012-13", "BRK"),  # Nets, permanent mismatch since the Brooklyn move
        ("BKN", "2025-26", "BRK"),  # Nets, still BRK in the modern era too
        ("CHA", "1984-85", "CHA"),  # unaffected pre-expansion year, passes through unchanged
        ("CHA", "2013-14", "CHA"),  # last season still under "CHA" (Bobcats era)
        ("CHA", "2014-15", "CHO"),  # Hornets rename season, bbref code changes too
        ("CHA", "2020-21", "CHO"),  # modern code stays CHO
    ],
)
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
    assert len(result["players"]) == 14
    assert result["players"][0]["player"] == "Paul Pierce"


def test_team_season_payroll_with_no_salary_table_is_none_not_zero(monkeypatch):
    # None, never 0: a real team's payroll is never actually zero, so 0 would be
    # indistinguishable from a genuine value once it reaches a chart.
    _fake_pages({"BOS": "<html><body>no table here</body></html>"}, monkeypatch)
    result = team_season_payroll("BOS", "1986-87")
    assert result["team_payroll"] is None
    assert result["player_count"] == 0
    assert result["players"] == []


def test_ingest_season_writes_a_row_for_a_team_with_no_data(monkeypatch):
    # The 1986-87/1989-90 source gap: a skipped team-season vanishes from the
    # parquet entirely, and a completeness flag can't fire for a row that
    # doesn't exist. Every requested team must produce a row.
    html = FIXTURE.read_text(encoding="utf-8")
    _fake_pages({"BOS": html, "DAL": "<html>nothing</html>"}, monkeypatch)
    df, players, failed = team_payroll_ingest.ingest_season("1986-87", ["BOS", "DAL"])

    assert failed == [], "no table is a result, not a failure"
    assert len(df) == 2
    assert sorted(df["team_abbreviation"]) == ["BOS", "DAL"]
    dal = df[df["team_abbreviation"] == "DAL"].iloc[0]
    assert dal["team_payroll"] is None or pd.isna(dal["team_payroll"])
    assert dal["player_count"] == 0
    bos = df[df["team_abbreviation"] == "BOS"].iloc[0]
    assert bos["team_payroll"] == 83552174
    assert bos["player_count"] == 14
    assert len(players) == 14
    assert set(players["team_abbreviation"]) == {"BOS"}


TOTAL_COLUMNS = ["season", "team_abbreviation", "team_payroll", "player_count", "fetched_at_utc"]
PLAYER_COLUMNS = [
    "season",
    "team_abbreviation",
    "bbref_player_id",
    "player",
    "salary_usd",
    "fetched_at_utc",
]


def test_ingest_season_columns(monkeypatch):
    _fake_pages({"BOS": FIXTURE.read_text(encoding="utf-8")}, monkeypatch)
    df, players, failed = team_payroll_ingest.ingest_season("2009-10", ["BOS"])
    assert failed == []
    assert list(df.columns) == TOTAL_COLUMNS
    assert list(players.columns) == PLAYER_COLUMNS
    # The two files describe the same scrape, so they must agree to the dollar.
    assert players["salary_usd"].sum() == df["team_payroll"].sum() == 83552174
    assert df["fetched_at_utc"].notna().all()
    assert players["fetched_at_utc"].notna().all()


def test_write_season_parquet_round_trips(tmp_path, monkeypatch):
    _fake_pages({"BOS": FIXTURE.read_text(encoding="utf-8"), "DAL": "<html>x</html>"}, monkeypatch)
    monkeypatch.setattr(team_payroll_ingest, "RAW_DIR", tmp_path / "team_payroll")
    monkeypatch.setattr(team_payroll_ingest, "PLAYERS_DIR", tmp_path / "team_payroll_players")
    team_payroll_ingest.write_season("2009-10", ["BOS", "DAL"])

    df = pd.read_parquet(tmp_path / "team_payroll" / "2009-10.parquet")
    assert list(df.columns) == TOTAL_COLUMNS
    assert set(df["player_count"]) == {0, 14}
    players = pd.read_parquet(tmp_path / "team_payroll_players" / "2009-10.parquet")
    assert list(players.columns) == PLAYER_COLUMNS
    assert len(players) == 14


def test_write_season_refetches_a_season_missing_its_player_file(tmp_path, monkeypatch):
    """Seasons backfilled before per-player rows were kept have only the
    totals file. Skipping them would leave the contracts list empty forever,
    so the skip needs both files present."""
    calls = []

    def fake_fetch(team_code, season):
        calls.append(team_code)
        return FIXTURE.read_text(encoding="utf-8")

    monkeypatch.setattr(team_payroll_ingest, "fetch_team_season_html", fake_fetch)
    monkeypatch.setattr(team_payroll_ingest, "RAW_DIR", tmp_path / "team_payroll")
    monkeypatch.setattr(team_payroll_ingest, "PLAYERS_DIR", tmp_path / "team_payroll_players")
    (tmp_path / "team_payroll").mkdir()
    pd.DataFrame({"season": ["2009-10"]}).to_parquet(tmp_path / "team_payroll" / "2009-10.parquet")

    team_payroll_ingest.write_season("2009-10", ["BOS"])
    assert calls == ["BOS"], "a season without its player file must be re-fetched"

    team_payroll_ingest.write_season("2009-10", ["BOS"])
    assert calls == ["BOS"], "with both files present the season is skipped"


def test_fetch_decodes_pages_as_utf8_even_without_a_declared_charset(monkeypatch):
    """Basketball-Reference serves UTF-8 with a bare "text/html" content type,
    and requests decodes that as ISO-8859-1 - which published "Luka DonÄ\x8diÄ\x87"
    for every accented name until the fetch forced UTF-8."""

    def fake_get(url, headers, timeout):
        resp = requests.Response()
        resp.status_code = 200
        resp.headers["Content-Type"] = "text/html"
        resp._content = "Luka Dončić".encode()
        # What requests' HTTP adapter does to every real response.
        resp.encoding = requests.utils.get_encoding_from_headers(resp.headers)
        return resp

    monkeypatch.setattr(team_payroll_ingest, "_throttle", lambda: None)
    monkeypatch.setattr(team_payroll_ingest.requests, "get", fake_get)
    assert team_payroll_ingest.fetch_team_season_html("DAL", "2023-24") == "Luka Dončić"


# --- retry policy -----------------------------------------------------------------

BOS_HTML = FIXTURE.read_text(encoding="utf-8")


def _response(status, body="", headers=None):
    resp = requests.Response()
    resp.status_code = status
    resp.headers.update(headers or {})
    resp._content = body.encode()
    resp.url = "https://www.basketball-reference.com/teams/BOS/2010.html"
    return resp


class FakeGet:
    """Plays one outcome per requests.get call: an exception or a Response."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def __call__(self, url, headers=None, timeout=None):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


@pytest.fixture
def sleeps(monkeypatch):
    waits = []
    monkeypatch.setattr(team_payroll_ingest, "_throttle", lambda: None)
    monkeypatch.setattr(core_io.time, "sleep", waits.append)
    return waits


def _fetch(monkeypatch, *outcomes):
    get = FakeGet(*outcomes)
    monkeypatch.setattr(team_payroll_ingest.requests, "get", get)
    return team_payroll_ingest.fetch_team_season_html("BOS", "2009-10"), get


def test_429_retry_after_is_honoured(monkeypatch, sleeps):
    html, get = _fetch(
        monkeypatch, _response(429, headers={"Retry-After": "17"}), _response(200, "ok")
    )
    assert html == "ok"
    assert get.calls == 2
    assert sleeps == [17.0]


def test_429_without_retry_after_backs_off_a_minute_then_doubles(monkeypatch, sleeps):
    with pytest.raises(core_io.TransientError):
        _fetch(monkeypatch, *[_response(429)] * team_payroll_ingest.MAX_RETRIES)
    assert len(sleeps) == team_payroll_ingest.MAX_RETRIES - 1
    for wait, floor in zip(sleeps, [60, 120, 240], strict=False):
        assert floor <= wait <= floor * 1.25


@pytest.mark.parametrize("status", [500, 502, 503])
def test_server_errors_are_retried(monkeypatch, sleeps, status):
    html, get = _fetch(monkeypatch, _response(status), _response(200, "ok"))
    assert html == "ok"
    assert get.calls == 2
    assert 6 <= sleeps[0] <= 7.5


@pytest.mark.parametrize("error", [requests.ConnectionError("reset"), requests.ReadTimeout("slow")])
def test_network_errors_are_retried(monkeypatch, sleeps, error):
    html, get = _fetch(monkeypatch, error, _response(200, "ok"))
    assert html == "ok"
    assert get.calls == 2


def test_404_is_not_retried_and_means_no_page(monkeypatch, sleeps):
    html, get = _fetch(monkeypatch, _response(404), _response(200, "ok"))
    assert html is None
    assert get.calls == 1
    assert sleeps == []


def test_403_is_not_retried(monkeypatch, sleeps):
    with pytest.raises(requests.HTTPError):
        _fetch(monkeypatch, _response(403), _response(200, "ok"))
    assert sleeps == []


def test_type_error_is_not_retried(monkeypatch, sleeps):
    get = FakeGet(TypeError("bad argument"), _response(200, "ok"))
    monkeypatch.setattr(team_payroll_ingest.requests, "get", get)
    with pytest.raises(TypeError):
        team_payroll_ingest.fetch_team_season_html("BOS", "2009-10")
    assert get.calls == 1
    assert sleeps == []


def test_a_404_team_gets_a_no_table_row(monkeypatch, sleeps):
    monkeypatch.setattr(team_payroll_ingest.requests, "get", FakeGet(_response(404)))
    result = team_season_payroll("BOS", "2009-10")
    assert result == {"team_payroll": None, "player_count": 0, "players": []}


# --- per-team isolation -----------------------------------------------------------


def _pages_or_errors(monkeypatch, pages):
    """Per bbref code: HTML to return, or the exception the fetch raises
    once its retries are spent."""

    def fake_fetch(team_code, season):
        page = pages[team_code]
        if isinstance(page, BaseException):
            raise page
        return page

    monkeypatch.setattr(team_payroll_ingest, "fetch_team_season_html", fake_fetch)


def test_one_failing_team_does_not_stop_the_others(monkeypatch, caplog):
    _pages_or_errors(
        monkeypatch,
        {
            "BOS": BOS_HTML,
            "DAL": requests.ConnectionError("reset"),
            "MIA": core_io.TransientError("HTTP 503", status=503),
            "LAL": "<html>no table</html>",
        },
    )
    with caplog.at_level(logging.ERROR, logger="team_payroll_ingest"):
        df, players, failed = team_payroll_ingest.ingest_season(
            "2009-10", ["BOS", "DAL", "MIA", "LAL"]
        )
    assert failed == ["DAL", "MIA"]
    assert sorted(df["team_abbreviation"]) == ["BOS", "LAL"]
    assert len(players) == 14
    assert "DAL" in caplog.text
    assert "MIA" in caplog.text


def test_a_bug_still_stops_the_run(monkeypatch):
    _pages_or_errors(monkeypatch, {"BOS": TypeError("bug"), "DAL": BOS_HTML})
    with pytest.raises(TypeError):
        team_payroll_ingest.ingest_season("2009-10", ["BOS", "DAL"])


@pytest.fixture
def raw(tmp_path, monkeypatch):
    monkeypatch.setattr(team_payroll_ingest, "RAW_DIR", tmp_path / "team_payroll")
    monkeypatch.setattr(team_payroll_ingest, "PLAYERS_DIR", tmp_path / "team_payroll_players")
    return tmp_path


def test_write_season_writes_the_teams_that_succeeded_and_reports_failure(monkeypatch, raw):
    _pages_or_errors(monkeypatch, {"BOS": BOS_HTML, "DAL": requests.ConnectionError("x")})
    assert team_payroll_ingest.write_season("2009-10", ["BOS", "DAL"]) is False

    df = pd.read_parquet(raw / "team_payroll" / "2009-10.parquet")
    assert df["team_abbreviation"].tolist() == ["BOS"]
    assert list((raw / "team_payroll").iterdir()) == [raw / "team_payroll" / "2009-10.parquet"]


def test_write_season_writes_nothing_when_every_team_failed(monkeypatch, raw):
    _pages_or_errors(monkeypatch, {"BOS": requests.ConnectionError("x")})
    assert team_payroll_ingest.write_season("2009-10", ["BOS"]) is False
    assert not (raw / "team_payroll" / "2009-10.parquet").exists()


def test_a_season_missing_a_team_is_fetched_again(monkeypatch, raw):
    # Without this a team that failed once would be missing for good: the
    # season's files exist, so the next run would skip the season.
    _pages_or_errors(monkeypatch, {"BOS": BOS_HTML, "DAL": requests.ConnectionError("x")})
    team_payroll_ingest.write_season("2009-10", ["BOS", "DAL"])

    _pages_or_errors(monkeypatch, {"BOS": BOS_HTML, "DAL": "<html>x</html>"})
    assert team_payroll_ingest.write_season("2009-10", ["BOS", "DAL"]) is True
    df = pd.read_parquet(raw / "team_payroll" / "2009-10.parquet")
    assert sorted(df["team_abbreviation"]) == ["BOS", "DAL"]


def test_a_corrupt_season_file_is_fetched_again(monkeypatch, raw, caplog):
    _pages_or_errors(monkeypatch, {"BOS": BOS_HTML})
    team_payroll_ingest.write_season("2009-10", ["BOS"])
    path = raw / "team_payroll" / "2009-10.parquet"
    path.write_bytes(path.read_bytes()[:30])  # a write killed halfway

    calls = []

    def fake_fetch(team_code, season):
        calls.append(team_code)
        return BOS_HTML

    monkeypatch.setattr(team_payroll_ingest, "fetch_team_season_html", fake_fetch)
    with caplog.at_level(logging.WARNING, logger="team_payroll_ingest"):
        assert team_payroll_ingest.write_season("2009-10", ["BOS"]) is True
    assert calls == ["BOS"]
    assert core_io.is_valid_parquet(path)
    assert "unreadable" in caplog.text


def test_main_exits_non_zero_when_a_team_failed(monkeypatch, raw):
    _pages_or_errors(monkeypatch, {"BOS": BOS_HTML, "DAL": requests.ConnectionError("x")})
    monkeypatch.setattr(
        "sys.argv", ["team_payroll_ingest.py", "--season", "2009-10", "--teams", "BOS", "DAL"]
    )
    with pytest.raises(SystemExit) as exc:
        team_payroll_ingest.main()
    assert exc.value.code == 1
    assert (raw / "team_payroll" / "2009-10.parquet").exists()


def test_main_exits_zero_when_every_team_succeeded(monkeypatch, raw):
    _pages_or_errors(monkeypatch, {"BOS": BOS_HTML})
    monkeypatch.setattr(
        "sys.argv", ["team_payroll_ingest.py", "--season", "2009-10", "--teams", "BOS"]
    )
    team_payroll_ingest.main()


# --- shrink guard -----------------------------------------------------------------


def test_force_refuses_to_replace_a_bigger_season(monkeypatch, raw, caplog):
    _pages_or_errors(monkeypatch, {"BOS": BOS_HTML, "DAL": "<html>x</html>"})
    team_payroll_ingest.write_season("2009-10", ["BOS", "DAL"])
    totals = raw / "team_payroll" / "2009-10.parquet"
    players = raw / "team_payroll_players" / "2009-10.parquet"
    before = (totals.read_bytes(), players.read_bytes())

    # DAL fails this time: the re-fetch has one team where the file has two.
    _pages_or_errors(monkeypatch, {"BOS": BOS_HTML, "DAL": requests.ConnectionError("x")})
    with caplog.at_level(logging.ERROR, logger="team_payroll_ingest"):
        assert team_payroll_ingest.write_season("2009-10", ["BOS", "DAL"], force=True) is False
    assert (totals.read_bytes(), players.read_bytes()) == before
    assert "--allow-shrink" in caplog.text


def test_force_refuses_fewer_salary_lines_and_keeps_both_files(monkeypatch, raw):
    # A layout change that hides the salary table keeps every team row but
    # drops every salary line - only the players file shows it.
    _pages_or_errors(monkeypatch, {"BOS": BOS_HTML})
    team_payroll_ingest.write_season("2009-10", ["BOS"])
    totals = raw / "team_payroll" / "2009-10.parquet"
    before = totals.read_bytes()

    _pages_or_errors(monkeypatch, {"BOS": "<html>layout changed</html>"})
    assert team_payroll_ingest.write_season("2009-10", ["BOS"], force=True) is False
    assert totals.read_bytes() == before
    assert len(pd.read_parquet(raw / "team_payroll_players" / "2009-10.parquet")) == 14


def test_allow_shrink_replaces_a_bigger_season(monkeypatch, raw):
    _pages_or_errors(monkeypatch, {"BOS": BOS_HTML})
    team_payroll_ingest.write_season("2009-10", ["BOS"])

    _pages_or_errors(monkeypatch, {"BOS": "<html>x</html>"})
    ok = team_payroll_ingest.write_season("2009-10", ["BOS"], force=True, allow_shrink=True)
    assert ok is True
    assert len(pd.read_parquet(raw / "team_payroll_players" / "2009-10.parquet")) == 0


def test_main_passes_allow_shrink(monkeypatch):
    seen = {}

    def fake_write(season, teams, force=False, allow_shrink=False):
        seen.update(force=force, allow_shrink=allow_shrink)
        return True

    monkeypatch.setattr(team_payroll_ingest, "write_season", fake_write)
    monkeypatch.setattr(
        "sys.argv",
        ["x", "--season", "2025-26", "--teams", "BOS", "--force", "--allow-shrink"],
    )
    team_payroll_ingest.main()
    assert seen == {"force": True, "allow_shrink": True}
