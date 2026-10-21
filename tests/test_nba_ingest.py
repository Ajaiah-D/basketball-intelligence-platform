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
        requests.exceptions.ChunkedEncodingError("connection reset mid-body"),
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


def test_a_response_without_a_readable_status_is_not_retried(monkeypatch, sleeps):
    """The status comes from nba_api's private _status_code. If a future
    nba_api drops it, a parse error must fail fast, not loop."""

    class NoStatusEndpoint:
        def __init__(self, timeout=None, get_request=True, **kwargs):
            self.nba_response = SimpleNamespace()  # no _status_code

        def get_request(self):
            raise ValueError("Expecting value: line 1 column 1 (char 0)")

    with pytest.raises(ValueError):
        nba_ingest.call_endpoint(NoStatusEndpoint, season="2025-26")
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


def _pbp(game_ids, per_game=3, note="new"):
    """Play-by-play rows the way PlayByPlayV3 returns them: actionNumber
    repeats within a game (a steal shares its turnover's), actionId doesn't."""
    return pd.DataFrame(
        [
            {
                "gameId": g,
                "actionNumber": 10 * (k // 2 + 1),
                "actionId": k + 1,
                "season": "2025-26",
                "note": note,
            }
            for g in game_ids
            for k in range(per_game)
        ]
    )


def _logs(game_ids):
    """Team game logs where the later ids are the more recent games."""
    return pd.DataFrame(
        {"GAME_ID": game_ids, "GAME_DATE": [f"2025-11-{i + 1:02d}" for i in range(len(game_ids))]}
    )


def _stub_fetchers_except_team_logs(monkeypatch):
    for name in (
        "fetch_player_game_logs",
        "fetch_player_advanced",
        "fetch_team_advanced",
        "fetch_schedule",
        "fetch_players",
    ):
        monkeypatch.setattr(nba_ingest, name, lambda s: _rows(3))
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


@pytest.mark.parametrize(
    "existing,new,written",
    [
        (20, 19, True),  # a 5% drop: the NBA corrected some rows
        (20, 15, False),  # a 25% drop
        (20, 0, False),  # an empty answer
    ],
)
def test_only_a_large_or_empty_shrink_is_refused(tmp_path, monkeypatch, existing, new, written):
    monkeypatch.setattr(nba_ingest, "RAW_DIR", tmp_path)
    _seed(tmp_path, "team_game_logs", "2025-26", existing)
    _stub_fetchers(monkeypatch, rows=new)

    refused = nba_ingest.run(["2025-26"], 0, force=True)

    rows = len(pd.read_parquet(tmp_path / "team_game_logs" / "2025-26.parquet"))
    assert rows == (new if written else existing)
    assert ("team_game_logs/2025-26" in refused) is not written


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


def test_play_by_play_is_not_shrink_guarded(tmp_path, monkeypatch):
    # run() only ever adds to it, so the guard has nothing to catch there.
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


def test_refused_team_logs_are_not_used_for_play_by_play(tmp_path, monkeypatch):
    """When the shrink guard keeps the old team logs, play-by-play must pick
    its games from that file, not from the short answer it just refused."""
    monkeypatch.setattr(nba_ingest, "RAW_DIR", tmp_path)
    (tmp_path / "team_game_logs").mkdir()
    on_disk = pd.DataFrame({"GAME_ID": [f"D{i:02d}" for i in range(10)], "GAME_DATE": "2025-11-01"})
    core_io.atomic_write_parquet(on_disk, tmp_path / "team_game_logs" / "2025-26.parquet")
    _stub_fetchers(monkeypatch, rows=4)  # GAME_IDs 000-003: a refused 60% drop
    picked = []

    def fake_pbp(game_ids, season):
        picked.extend(game_ids)
        return _pbp(game_ids)

    monkeypatch.setattr(nba_ingest, "fetch_play_by_play", fake_pbp)

    refused = nba_ingest.run(["2025-26"], 20, force=True)

    assert "team_game_logs/2025-26" in refused
    assert sorted(picked) == sorted(on_disk["GAME_ID"])


# --- play-by-play accumulates -----------------------------------------------------

SEASON = "2025-26"


def _game_ids(n):
    """Ids G00..G{n-1}, G{n-1} being the most recent game."""
    return [f"G{i:02d}" for i in range(n)]


def _pbp_run(tmp_path, monkeypatch, *, played, stored=(), pbp_games=None, fetch=None):
    """Run the latest season with `played` games in the team logs and
    `stored` ones already in the play-by-play file. Returns the ids fetched."""
    monkeypatch.setattr(nba_ingest, "RAW_DIR", tmp_path)
    _stub_fetchers_except_team_logs(monkeypatch)
    monkeypatch.setattr(nba_ingest, "fetch_team_game_logs", lambda s: _logs(played))
    if stored:
        (tmp_path / "play_by_play").mkdir()
        core_io.atomic_write_parquet(
            _pbp(stored, note="old"), tmp_path / "play_by_play" / f"{SEASON}.parquet"
        )
    fetched: list[str] = []

    def fake_fetch(game_ids, season):
        fetched.extend(game_ids)
        return _pbp(game_ids)

    monkeypatch.setattr(nba_ingest, "fetch_play_by_play", fetch or fake_fetch)
    nba_ingest.run([SEASON], pbp_games, force=True)
    return fetched


def _stored_pbp(tmp_path):
    return pd.read_parquet(tmp_path / "play_by_play" / f"{SEASON}.parquet")


def test_only_games_missing_from_the_file_are_fetched(tmp_path, monkeypatch):
    ids = _game_ids(6)
    fetched = _pbp_run(tmp_path, monkeypatch, played=ids, stored=ids[:3], pbp_games=20)
    # Newest first, and none of the three already stored.
    assert fetched == ["G05", "G04", "G03"]


def test_stored_games_are_kept_when_new_ones_arrive(tmp_path, monkeypatch):
    ids = _game_ids(5)
    _pbp_run(tmp_path, monkeypatch, played=ids, stored=ids[:3], pbp_games=20)

    out = _stored_pbp(tmp_path)
    assert sorted(out["gameId"].unique()) == ids
    # The old rows are the stored ones, not a re-fetch of them.
    assert set(out[out["gameId"].isin(ids[:3])]["note"]) == {"old"}
    assert set(out[out["gameId"].isin(ids[3:])]["note"]) == {"new"}


def test_a_fully_stored_season_fetches_nothing_and_changes_nothing(tmp_path, monkeypatch):
    ids = _game_ids(3)
    fetched = _pbp_run(tmp_path, monkeypatch, played=ids, stored=ids, pbp_games=20)
    assert fetched == []
    assert len(_stored_pbp(tmp_path)) == 9


def test_rows_are_not_duplicated(tmp_path, monkeypatch):
    ids = _game_ids(3)

    def overlapping(game_ids, season):
        # A source that repeats a stored game, and one of its own games.
        return pd.concat([_pbp(game_ids), _pbp(["G00"]), _pbp(game_ids[:1])], ignore_index=True)

    _pbp_run(tmp_path, monkeypatch, played=ids, stored=ids[:1], pbp_games=20, fetch=overlapping)

    out = _stored_pbp(tmp_path)
    assert not out.duplicated(["gameId", "actionNumber", "actionId"]).any()
    assert len(out) == 9


def test_two_events_sharing_an_action_number_both_survive(tmp_path, monkeypatch):
    # actionNumber alone is not a key: a steal shares its turnover's number.
    ids = _game_ids(2)
    _pbp_run(tmp_path, monkeypatch, played=ids, stored=ids[:1], pbp_games=20)

    out = _stored_pbp(tmp_path)
    assert out.duplicated(["gameId", "actionNumber"]).any()
    assert len(out) == 6


def test_no_more_than_the_cap_is_fetched_per_run(tmp_path, monkeypatch):
    ids = _game_ids(10)
    fetched = _pbp_run(tmp_path, monkeypatch, played=ids, stored=ids[:2], pbp_games=3)

    assert fetched == ["G09", "G08", "G07"]
    assert sorted(_stored_pbp(tmp_path)["gameId"].unique()) == ["G00", "G01", "G07", "G08", "G09"]


def test_without_a_cap_every_missing_game_is_fetched(tmp_path, monkeypatch):
    ids = _game_ids(10)
    fetched = _pbp_run(tmp_path, monkeypatch, played=ids, stored=ids[:2], pbp_games=None)
    assert len(fetched) == 8


def test_an_unreadable_file_is_started_afresh(tmp_path, monkeypatch):
    ids = _game_ids(3)
    (tmp_path / "play_by_play").mkdir()
    (tmp_path / "play_by_play" / f"{SEASON}.parquet").write_bytes(b"PAR1 truncated")
    fetched = _pbp_run(tmp_path, monkeypatch, played=ids, pbp_games=20)
    assert sorted(fetched) == ids
    assert len(_stored_pbp(tmp_path)) == 9


def test_play_by_play_failing_for_every_game_does_not_stop_the_run(tmp_path, monkeypatch, caplog):
    ids = _game_ids(4)
    monkeypatch.setattr(nba_ingest, "RAW_DIR", tmp_path)
    monkeypatch.setattr(nba_ingest, "fetch_team_game_logs", lambda s: _logs(ids))
    _stub_fetchers_except_team_logs(monkeypatch)
    (tmp_path / "play_by_play").mkdir()
    core_io.atomic_write_parquet(
        _pbp(ids[:2], note="old"), tmp_path / "play_by_play" / f"{SEASON}.parquet"
    )

    def always_fails(endpoint_cls, **kwargs):
        raise ValueError("not JSON")

    monkeypatch.setattr(nba_ingest, "call_endpoint", always_fails)
    written = []
    real_write = nba_ingest.write_parquet

    def spy_write(df, name, season=None, **kwargs):
        written.append(name)
        return real_write(df, name, season, **kwargs)

    monkeypatch.setattr(nba_ingest, "write_parquet", spy_write)

    with caplog.at_level(logging.WARNING, logger="nba_ingest"):
        refused = nba_ingest.run([SEASON], 20, force=True)

    assert refused == []
    assert "play_by_play" not in written
    # What was stored stays, and the core data landed.
    assert len(_stored_pbp(tmp_path)) == 6
    assert (tmp_path / "players.parquet").exists()
    assert (tmp_path / "teams.parquet").exists()
    assert (tmp_path / "team_game_logs" / f"{SEASON}.parquet").exists()
    assert "play-by-play" in caplog.text.lower()


def test_play_by_play_is_fetched_and_written_after_the_core_files(tmp_path, monkeypatch):
    ids = _game_ids(3)
    events = []
    monkeypatch.setattr(nba_ingest, "RAW_DIR", tmp_path)
    monkeypatch.setattr(nba_ingest, "fetch_team_game_logs", lambda s: _logs(ids))
    _stub_fetchers_except_team_logs(monkeypatch)
    real_write = nba_ingest.write_parquet

    def spy_write(df, name, season=None, **kwargs):
        events.append(f"write {name}")
        return real_write(df, name, season, **kwargs)

    def spy_fetch(game_ids, season):
        events.append("fetch play_by_play")
        return _pbp(game_ids)

    monkeypatch.setattr(nba_ingest, "write_parquet", spy_write)
    monkeypatch.setattr(nba_ingest, "fetch_play_by_play", spy_fetch)

    nba_ingest.run([SEASON], 20, force=True)

    assert events[-2:] == ["fetch play_by_play", "write play_by_play"]
    core = {
        "write player_game_logs",
        "write team_game_logs",
        "write player_advanced",
        "write team_advanced",
        "write schedule",
        "write players",
        "write teams",
    }
    assert core <= set(events[:-2])


def test_fetch_play_by_play_returns_nothing_rather_than_raising(monkeypatch):
    def always_fails(*args, **kwargs):
        raise ValueError("bad")

    monkeypatch.setattr(nba_ingest, "call_endpoint", always_fails)
    assert nba_ingest.fetch_play_by_play(["G00", "G01"], SEASON).empty


def test_the_cli_default_is_the_shared_cap():
    from core.constants import PBP_MAX_NEW_GAMES_PER_RUN

    args = nba_ingest.build_parser().parse_args([])
    assert args.pbp_games == PBP_MAX_NEW_GAMES_PER_RUN == 120


def test_a_file_without_a_game_id_column_is_started_afresh(tmp_path, monkeypatch, caplog):
    ids = _game_ids(2)
    (tmp_path / "play_by_play").mkdir()
    core_io.atomic_write_parquet(
        pd.DataFrame({"unrelated": [1, 2]}), tmp_path / "play_by_play" / f"{SEASON}.parquet"
    )
    with caplog.at_level(logging.WARNING, logger="nba_ingest"):
        fetched = _pbp_run(tmp_path, monkeypatch, played=ids, pbp_games=20)
    assert sorted(fetched) == ids
    assert len(_stored_pbp(tmp_path)) == 6
    assert "no gameId column" in caplog.text


def test_games_that_fail_or_come_back_empty_are_counted(monkeypatch, caplog):
    def endpoint(endpoint_cls, game_id):
        if game_id == "G00":
            raise ValueError("not JSON")
        if game_id == "G01":
            return pd.DataFrame()
        return _pbp([game_id])

    monkeypatch.setattr(nba_ingest, "call_endpoint", endpoint)
    with caplog.at_level(logging.WARNING, logger="nba_ingest"):
        out = nba_ingest.fetch_play_by_play(_game_ids(4), SEASON)

    assert sorted(out["gameId"].unique()) == ["G02", "G03"]
    assert "1 of 4 games failed and 1 returned no rows" in caplog.text
