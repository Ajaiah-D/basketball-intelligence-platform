"""core.io: crash-safe parquet writes, footer checks and the transient-only
retry loop both ingesters share. Nothing here touches the network."""

import logging

import pandas as pd
import pyarrow as pa
import pytest

from core import io as core_io

log = logging.getLogger("test_core_io")


def _frame(rows: int) -> pd.DataFrame:
    return pd.DataFrame({"a": range(rows), "b": [f"x{i}" for i in range(rows)]})


# --- atomic_write_parquet ------------------------------------------------------


def test_atomic_write_round_trips_and_leaves_no_tmp(tmp_path):
    path = tmp_path / "sub" / "2025-26.parquet"
    path.parent.mkdir()
    core_io.atomic_write_parquet(_frame(5), path)

    assert pd.read_parquet(path).equals(_frame(5))
    assert list(path.parent.iterdir()) == [path]


def test_atomic_write_replaces_an_existing_file(tmp_path):
    path = tmp_path / "f.parquet"
    core_io.atomic_write_parquet(_frame(5), path)
    core_io.atomic_write_parquet(_frame(2), path)
    assert len(pd.read_parquet(path)) == 2
    assert list(tmp_path.iterdir()) == [path]


def test_a_crash_mid_write_keeps_the_original(tmp_path, monkeypatch):
    path = tmp_path / "f.parquet"
    core_io.atomic_write_parquet(_frame(5), path)

    def crash(*args, **kwargs):
        raise OSError("disk full")

    # The crash lands after the temp file is written, before it is swapped in.
    monkeypatch.setattr(core_io.os, "replace", crash)
    with pytest.raises(OSError, match="disk full"):
        core_io.atomic_write_parquet(_frame(1), path)

    assert pd.read_parquet(path).equals(_frame(5))
    assert list(tmp_path.iterdir()) == [path], "the temp file must be cleaned up"


def test_a_failed_serialisation_keeps_the_original(tmp_path):
    path = tmp_path / "f.parquet"
    core_io.atomic_write_parquet(_frame(3), path)
    # A column pyarrow can't serialise fails inside to_parquet itself.
    bad = pd.DataFrame({"a": [object(), object()]})
    with pytest.raises(pa.ArrowInvalid):
        core_io.atomic_write_parquet(bad, path)
    assert len(pd.read_parquet(path)) == 3
    assert list(tmp_path.iterdir()) == [path]


# --- is_valid_parquet / parquet_row_count --------------------------------------


def test_valid_parquet_and_row_count(tmp_path):
    path = tmp_path / "f.parquet"
    core_io.atomic_write_parquet(_frame(7), path)
    assert core_io.is_valid_parquet(path)
    assert core_io.parquet_row_count(path) == 7


def test_an_empty_frame_is_still_a_valid_file(tmp_path):
    path = tmp_path / "f.parquet"
    core_io.atomic_write_parquet(_frame(0), path)
    assert core_io.is_valid_parquet(path)
    assert core_io.parquet_row_count(path) == 0


def test_missing_file_is_not_valid(tmp_path):
    path = tmp_path / "nope.parquet"
    assert not core_io.is_valid_parquet(path)
    assert core_io.parquet_row_count(path) is None


def test_truncated_file_is_not_valid(tmp_path):
    path = tmp_path / "f.parquet"
    core_io.atomic_write_parquet(_frame(50), path)
    # What a killed non-atomic write leaves behind: the head of the file
    # without its footer.
    path.write_bytes(path.read_bytes()[:100])
    assert not core_io.is_valid_parquet(path)
    assert core_io.parquet_row_count(path) is None


def test_garbage_and_directories_are_not_valid(tmp_path):
    junk = tmp_path / "junk.parquet"
    junk.write_bytes(b"<html>not parquet</html>")
    assert not core_io.is_valid_parquet(junk)
    folder = tmp_path / "dir.parquet"
    folder.mkdir()
    assert not core_io.is_valid_parquet(folder)
    assert core_io.parquet_row_count(folder) is None


# --- retry_after_seconds / backoff_delay ---------------------------------------


@pytest.mark.parametrize(
    "header,expected",
    [("30", 30.0), (" 7 ", 7.0), ("0", 0.0), (None, None), ("", None), ("-5", None)],
)
def test_retry_after_seconds(header, expected):
    assert core_io.retry_after_seconds(header) == expected


def test_retry_after_as_an_http_date_falls_back_to_backoff():
    assert core_io.retry_after_seconds("Wed, 21 Oct 2026 07:28:00 GMT") is None


def test_backoff_doubles_with_bounded_jitter():
    for attempt, floor in [(1, 60), (2, 120), (3, 240)]:
        delays = [core_io.backoff_delay(60, attempt) for _ in range(200)]
        assert all(floor <= d <= floor * 1.25 for d in delays)
        assert len(set(delays)) > 1, "jitter should spread retries out"


# --- retry_transient ------------------------------------------------------------


class Flaky:
    """Raises each queued exception in turn, then returns "ok"."""

    def __init__(self, *errors: BaseException):
        self.errors = list(errors)
        self.calls = 0

    def __call__(self) -> str:
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return "ok"


class FlakyError(Exception):
    pass


@pytest.fixture
def sleeps(monkeypatch):
    waits: list[float] = []
    monkeypatch.setattr(core_io.time, "sleep", waits.append)
    return waits


def _retry(call, attempts=3):
    return core_io.retry_transient(
        call,
        attempts=attempts,
        transient=(FlakyError, core_io.TransientError),
        delay=lambda exc, attempt: 10.0 * attempt,
        label="thing",
        log=log,
    )


def test_transient_errors_are_retried_then_succeed(sleeps):
    call = Flaky(FlakyError(), FlakyError())
    assert _retry(call) == "ok"
    assert call.calls == 3
    assert sleeps == [10.0, 20.0]


def test_the_last_transient_error_is_raised_after_all_attempts(sleeps):
    call = Flaky(FlakyError("1"), FlakyError("2"), FlakyError("3"))
    with pytest.raises(FlakyError, match="3"):
        _retry(call)
    assert call.calls == 3
    assert sleeps == [10.0, 20.0], "no sleep after the final attempt"


@pytest.mark.parametrize("error", [TypeError("bug"), KeyError("col"), ValueError("bad")])
def test_non_transient_errors_are_not_retried(sleeps, error):
    call = Flaky(error)
    with pytest.raises(type(error)):
        _retry(call)
    assert call.calls == 1
    assert sleeps == []


def test_retry_after_on_a_transient_error_wins_over_the_backoff(sleeps):
    call = Flaky(core_io.TransientError("429", status=429, retry_after=42.0))
    assert _retry(call) == "ok"
    assert sleeps == [42.0]
