"""Crash-safe parquet files and a retry loop that only retries what is worth
retrying. Shared by both ingesters.

A plain to_parquet() killed halfway (Ctrl-C, a reboot, a full disk) leaves a
file without its footer that still "exists", so the skip-if-done checks
treated a broken season as finished and never fetched it again. Writes now go
to a temp file that is swapped in whole, and "done" means the footer reads.

Deliberately free of requests: each ingester decides which of its own
exceptions are transient and passes them in.
"""

from __future__ import annotations

import contextlib
import logging
import os
import random
import time
from collections.abc import Callable
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

# Up to +25% on each backoff, so a batch of clients that failed together
# don't all come back in the same second.
JITTER = 0.25


def atomic_write_parquet(df: pd.DataFrame, path: Path) -> None:
    """Write to <path>.tmp in the same directory, fsync, then os.replace onto path.

    The old file stays untouched until the new one is complete on disk, and a
    failed write removes its temp file. The temp file keeps a .tmp suffix so
    the loader's *.parquet glob never picks one up.
    """
    tmp = path.with_name(path.name + ".tmp")
    try:
        df.to_parquet(tmp, index=False)
        # r+b, not rb: Windows only flushes a handle opened for writing.
        with tmp.open("r+b") as f:
            os.fsync(f.fileno())
        tmp.replace(path)  # os.replace: atomic on the same volume, Windows included
    finally:
        # Only still there when something above failed.
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()


def parquet_row_count(path: Path) -> int | None:
    """Row count from the footer, or None when missing/unreadable."""
    if not path.is_file():
        return None
    try:
        return int(pq.read_metadata(path).num_rows)
    except (OSError, pa.ArrowException):
        return None


def is_valid_parquet(path: Path) -> bool:
    """True when the file exists and its footer reads (pyarrow.parquet.read_metadata)."""
    return parquet_row_count(path) is not None


# The shrink guard is there to catch a broken, empty or partial answer, not
# every smaller one. Real data does shrink a little between fetches: the NBA
# corrects and removes box score rows, and a waived or traded player drops
# off a team's Basketball-Reference salary table. Losing more than a fifth
# of a file at once is not that.
SHRINK_GUARD_MIN_RATIO = 0.8


def suspicious_shrink(new_rows: int, existing_rows: int | None) -> bool:
    """True when replacing a file of existing_rows with new_rows looks like a
    broken fetch: the new frame is empty, or under SHRINK_GUARD_MIN_RATIO of
    the existing rows. False when there is no readable file to protect."""
    if not existing_rows:
        return False
    return new_rows == 0 or new_rows < existing_rows * SHRINK_GUARD_MIN_RATIO


class TransientError(Exception):
    """An HTTP answer that says "try again later": a 5xx or a 429.

    retry_after is the server's Retry-After in seconds, when it sent one.
    """

    def __init__(self, message: str, *, status: int, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


def is_transient_status(status: int) -> bool:
    """True for the HTTP statuses worth retrying: 429 and any 5xx."""
    return status == 429 or 500 <= status < 600


def retry_after_seconds(header: str | None) -> float | None:
    """A Retry-After header given in seconds, or None.

    The HTTP-date form is not parsed - neither site sends it - so it falls
    back to the caller's own backoff, as a missing header does.
    """
    if not header:
        return None
    try:
        seconds = float(header.strip())
    except ValueError:
        return None
    return seconds if seconds >= 0 else None


def backoff_delay(base: float, attempt: int) -> float:
    """base, 2*base, 4*base ... for attempt 1, 2, 3 ..., plus up to 25% jitter."""
    delay = base * 2 ** (attempt - 1)
    return delay * (1 + random.uniform(0, JITTER))


def retry_transient[T](
    call: Callable[[], T],
    *,
    attempts: int,
    transient: tuple[type[BaseException], ...],
    delay: Callable[[BaseException, int], float],
    label: str,
    log: logging.Logger,
    max_retry_after: float | None = None,
) -> T:
    """Run call(), retrying only the exception types in `transient`.

    Anything else - a TypeError, a KeyError, a 404 - propagates on the first
    attempt: retrying a bug or a missing page only delays the same failure.
    The wait before retry n is the error's retry_after when it carries one,
    else delay(exc, n). A retry_after over max_retry_after is not waited
    out: the error is re-raised at once, and the caller counts the request
    as failed for this run. The last attempt's error is re-raised as-is.
    """
    for attempt in range(1, attempts + 1):
        try:
            return call()
        except transient as exc:
            retry_after = getattr(exc, "retry_after", None)
            if (
                retry_after is not None
                and max_retry_after is not None
                and retry_after > max_retry_after
            ):
                log.warning(
                    "%s: server asked for a %.0fs wait (over the %.0fs cap) - giving up",
                    label,
                    retry_after,
                    max_retry_after,
                )
                raise
            if attempt == attempts:
                raise
            wait = retry_after if retry_after is not None else delay(exc, attempt)
            log.warning(
                "%s failed (attempt %d/%d): %s -- retrying in %.0fs",
                label,
                attempt,
                attempts,
                exc,
                wait,
            )
            time.sleep(wait)
    raise RuntimeError("unreachable")
