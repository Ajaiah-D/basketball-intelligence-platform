"""ingestion/nba_ingest.py: the retry policy, the season-done check and the
shrink guard, plus run() around the season rollover. Nothing reaches
stats.nba.com: either the fetchers are stubbed out, or nba_api's own HTTP
session is swapped for a fake so the real endpoint classes parse canned
responses."""

import json
import logging
from types import SimpleNamespace

import pandas as pd
import pytest
import requests
from nba_api.stats.endpoints import leaguegamelog
from nba_api.stats.library.http import NBAStatsHTTP

from core import io as core_io
from ingestion import nba_ingest


def test_a_season_with_no_games_yet_skips_play_by_play(monkeypatch):
    """From October 1 current_season() is the new season, but it has no
    games until opening night three weeks later. Play-by-play used to raise
    "No play-by-play data could be fetched" on the empty game list, failing
    the weekly refresh every October before tip-off."""
    empty_logs = pd.DataFrame(columns=["GAME_ID", "GAME_DATE", "TEAM_ABBREVIATION"])
    written = []

    def no_call(*args, **kwargs):
        raise AssertionError("play-by-play must not be fetched for an empty season")

    monkeypatch.setattr(nba_ingest, "fetch_player_game_logs", lambda s: empty_logs)
    monkeypatch.setattr(nba_ingest, "fetch_team_game_logs", lambda s: empty_logs)
    monkeypatch.setattr(nba_ingest, "fetch_player_advanced", lambda s: pd.DataFrame())
    monkeypatch.setattr(nba_ingest, "fetch_team_advanced", lambda s: pd.DataFrame())
    monkeypatch.setattr(nba_ingest, "fetch_schedule", lambda s: pd.DataFrame())
    monkeypatch.setattr(nba_ingest, "fetch_players", lambda s: pd.DataFrame())
    monkeypatch.setattr(nba_ingest, "fetch_teams", lambda: pd.DataFrame())
    monkeypatch.setattr(nba_ingest, "fetch_play_by_play", no_call)
    monkeypatch.setattr(
        nba_ingest,
        "write_parquet",
        lambda df, name, season=None, **kwargs: written.append((name, season)),
    )

    nba_ingest.run(["2026-27"], 20, force=True)

    assert ("play_by_play", "2026-27") not in written
    assert ("team_game_logs", "2026-27") in written


# --- call_endpoint retry policy ------------------------------------------------

GAME_LOG_BODY = json.dumps(
    {
        "resultSets": [
            {"name": "LeagueGameLog", "headers": ["GAME_ID", "PTS"], "rowSet": [["001", 110]]}
        ]
    }
)


class FakeSession:
    """Stands in for nba_api's requests.Session: each get() plays the next
    outcome - an exception to raise, or a (status, body) response."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def get(self, url, params=None, headers=None, proxies=None, timeout=None):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        status, body = outcome
        return SimpleNamespace(url=url, status_code=status, text=body)


@pytest.fixture
def sleeps(monkeypatch):
    waits = []
    monkeypatch.setattr(nba_ingest, "_throttle", lambda: None)
    monkeypatch.setattr(core_io.time, "sleep", waits.append)
    return waits


def _call(monkeypatch, *outcomes):
    session = FakeSession(*outcomes)
    monkeypatch.setattr(NBAStatsHTTP, "_session", session)
    df = nba_ingest.call_endpoint(
        leaguegamelog.LeagueGameLog, season="2025-26", player_or_team_abbreviation="T"
    )
    return df, session


@pytest.mark.parametrize(
    "error",
    [
        requests.ReadTimeout("read timed out"),
        requests.ConnectTimeout("connect timed out"),
        requests.ConnectionError("connection reset"),
    ],
)
def test_network_errors_are_retried(monkeypatch, sleeps, error):
    df, session = _call(monkeypatch, error, (200, GAME_LOG_BODY))
    assert session.calls == 2
    assert df["GAME_ID"].tolist() == ["001"]
    assert len(sleeps) == 1
    assert 4 <= sleeps[0] <= 5, "first backoff is 4s plus jitter"


@pytest.mark.parametrize("status", [500, 502, 503, 504, 429])
def test_server_errors_and_rate_limits_are_retried(monkeypatch, sleeps, status):
    # nba_api never checks the status: an error page reaches us as a JSON
    # decode error, and only the status says it was the server failing.
    df, session = _call(monkeypatch, (status, "<html>busy</html>"), (200, GAME_LOG_BODY))
    assert session.calls == 2
    assert len(df) == 1


def test_stats_nba_error_json_with_a_5xx_is_retried(monkeypatch, sleeps):
    # nba_api rewrites this body to XML before parsing it.
    df, session = _call(
        monkeypatch, (500, '{"Message":"An error has occurred."}'), (200, GAME_LOG_BODY)
    )
    assert session.calls == 2
    assert len(df) == 1


def test_backoff_grows_and_the_last_error_is_raised(monkeypatch, sleeps):
    with pytest.raises(core_io.TransientError):
        _call(monkeypatch, *[(503, "")] * nba_ingest.MAX_RETRIES)
    assert len(sleeps) == nba_ingest.MAX_RETRIES - 1
    for wait, floor in zip(sleeps, [4, 8, 16], strict=False):
        assert floor <= wait <= floor * 1.25


@pytest.mark.parametrize("status", [200, 400, 404])
def test_a_non_json_answer_without_a_server_error_is_not_retried(monkeypatch, sleeps, status):
    # A 200 or 4xx that isn't JSON is a wrong request or a moved endpoint;
    # asking again gets the same page.
    with pytest.raises(ValueError):
        _call(monkeypatch, (status, "<html>nope</html>"), (200, GAME_LOG_BODY))
    assert sleeps == []


def test_a_response_missing_its_result_set_is_not_retried(monkeypatch, sleeps):
    with pytest.raises(KeyError):
        _call(monkeypatch, (200, json.dumps({"resultSets": []})), (200, GAME_LOG_BODY))
    assert sleeps == []


def test_type_error_is_not_retried(monkeypatch, sleeps):
    calls = []

    def bad_endpoint(**kwargs):
        calls.append(kwargs)
        raise TypeError("unexpected keyword argument 'sesaon'")

    with pytest.raises(TypeError):
        nba_ingest.call_endpoint(bad_endpoint, sesaon="2025-26")
    assert len(calls) == 1
    assert sleeps == []


def test_an_empty_result_is_returned_not_retried(monkeypatch, sleeps):
    body = json.dumps(
        {"resultSets": [{"name": "LeagueGameLog", "headers": ["GAME_ID"], "rowSet": []}]}
    )
    df, session = _call(monkeypatch, (200, body))
    assert df.empty
    assert session.calls == 1


# --- season_done ----------------------------------------------------------------


def test_a_corrupt_season_file_is_not_done(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(nba_ingest, "RAW_DIR", tmp_path)
    (tmp_path / "team_game_logs").mkdir()
    path = tmp_path / "team_game_logs" / "2001-02.parquet"

    assert not nba_ingest.season_done("team_game_logs", "2001-02")

    core_io.atomic_write_parquet(pd.DataFrame({"x": [1, 2]}), path)
    assert nba_ingest.season_done("team_game_logs", "2001-02")

    path.write_bytes(path.read_bytes()[:20])  # a write killed halfway
    with caplog.at_level(logging.WARNING, logger="nba_ingest"):
        assert not nba_ingest.season_done("team_game_logs", "2001-02")
    assert "2001-02" in caplog.text


def test_write_parquet_leaves_no_temp_file(tmp_path, monkeypatch):
    monkeypatch.setattr(nba_ingest, "RAW_DIR", tmp_path)
    path = nba_ingest.write_parquet(pd.DataFrame({"x": [1]}), "schedule", "2025-26")
    assert path == tmp_path / "schedule" / "2025-26.parquet"
    assert list(path.parent.iterdir()) == [path]


# --- shrink guard ------------------------------------------------------------------


def _rows(n):
    return pd.DataFrame({"GAME_ID": [f"{i:03d}" for i in range(n)], "GAME_DATE": "2025-11-01"})


def _stub_fetchers(monkeypatch, rows):
    for name in (
        "fetch_player_game_logs",
        "fetch_team_game_logs",
        "fetch_player_advanced",
        "fetch_team_advanced",
        "fetch_schedule",
        "fetch_players",
    ):
        monkeypatch.setattr(nba_ingest, name, lambda s, n=rows: _rows(n))
    monkeypatch.setattr(nba_ingest, "fetch_teams", lambda: _rows(30))


def _seed(tmp_path, name, season, n):
    (tmp_path / name).mkdir(exist_ok=True)
    core_io.atomic_write_parquet(_rows(n), tmp_path / name / f"{season}.parquet")


def test_a_smaller_refetch_does_not_replace_the_season_file(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(nba_ingest, "RAW_DIR", tmp_path)
    _seed(tmp_path, "team_game_logs", "2025-26", 10)
    _seed(tmp_path, "schedule", "2025-26", 10)
    _stub_fetchers(monkeypatch, rows=4)

    with caplog.at_level(logging.ERROR, logger="nba_ingest"):
        refused = nba_ingest.run(["2025-26"], 0, force=True)

    assert sorted(refused) == ["schedule/2025-26", "team_game_logs/2025-26"]
    assert len(pd.read_parquet(tmp_path / "team_game_logs" / "2025-26.parquet")) == 10
    assert len(pd.read_parquet(tmp_path / "schedule" / "2025-26.parquet")) == 10
    # Files with nothing to protect still got written.
    assert len(pd.read_parquet(tmp_path / "player_game_logs" / "2025-26.parquet")) == 4
    assert len(pd.read_parquet(tmp_path / "players.parquet")) == 4
    assert "--allow-shrink" in caplog.text


def test_allow_shrink_replaces_the_file(tmp_path, monkeypatch):
    monkeypatch.setattr(nba_ingest, "RAW_DIR", tmp_path)
    _seed(tmp_path, "team_game_logs", "2025-26", 10)
    _stub_fetchers(monkeypatch, rows=4)

    assert nba_ingest.run(["2025-26"], 0, force=True, allow_shrink=True) == []
    assert len(pd.read_parquet(tmp_path / "team_game_logs" / "2025-26.parquet")) == 4


def test_equal_or_larger_refetch_replaces_the_file(tmp_path, monkeypatch):
    monkeypatch.setattr(nba_ingest, "RAW_DIR", tmp_path)
    _seed(tmp_path, "team_game_logs", "2025-26", 4)
    _stub_fetchers(monkeypatch, rows=6)

    assert nba_ingest.run(["2025-26"], 0, force=True) == []
    assert len(pd.read_parquet(tmp_path / "team_game_logs" / "2025-26.parquet")) == 6


def test_a_corrupt_existing_file_is_replaced_whatever_the_count(tmp_path, monkeypatch):
    monkeypatch.setattr(nba_ingest, "RAW_DIR", tmp_path)
    (tmp_path / "team_game_logs").mkdir()
    (tmp_path / "team_game_logs" / "2025-26.parquet").write_bytes(b"PAR1 truncated")
    _stub_fetchers(monkeypatch, rows=3)

    assert nba_ingest.run(["2025-26"], 0, force=True) == []
    assert len(pd.read_parquet(tmp_path / "team_game_logs" / "2025-26.parquet")) == 3


def test_play_by_play_may_shrink(tmp_path, monkeypatch):
    # Its size follows --pbp-games, so a smaller file is the normal case.
    monkeypatch.setattr(nba_ingest, "RAW_DIR", tmp_path)
    _seed(tmp_path, "play_by_play", "2025-26", 10)
    nba_ingest.write_parquet(_rows(2), "play_by_play", "2025-26")
    assert len(pd.read_parquet(tmp_path / "play_by_play" / "2025-26.parquet")) == 2


def test_main_exits_non_zero_after_a_refused_write(monkeypatch):
    seen = {}

    def fake_run(seasons, pbp_games, smoke_test=False, force=False, allow_shrink=False):
        seen["allow_shrink"] = allow_shrink
        return ["team_game_logs/2025-26"]

    monkeypatch.setattr(nba_ingest, "run", fake_run)
    monkeypatch.setattr("sys.argv", ["nba_ingest.py", "--season", "2025-26", "--force"])
    with pytest.raises(SystemExit) as exc:
        nba_ingest.main()
    assert exc.value.code == 1
    assert seen["allow_shrink"] is False

    monkeypatch.setattr(nba_ingest, "run", lambda *a, **k: seen.update(k) or [])
    monkeypatch.setattr("sys.argv", ["nba_ingest.py", "--season", "2025-26", "--allow-shrink"])
    nba_ingest.main()
    assert seen["allow_shrink"] is True
