"""Where the dashboard's data comes from, and how query results are cached.

Every query opens a fresh read-only DuckDB connection and closes it again.
A long-lived connection would hold the file open, which on Windows locks it
and blocks the weekly refresh from swapping a new warehouse into place; a
fresh read-only connection costs a few milliseconds, which the result cache
below hides anyway.

Results are cached with st.cache_data on the SQL, its parameters, the
warehouse path and the file's mtime. A swapped-in warehouse has a new mtime,
so nothing cached from the old file can be served for it, even before
clear_caches() runs.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import duckdb
import pandas as pd
import streamlit as st

from core import paths

CACHE_TTL_SECONDS = 600

# Set by use_warehouse(); None means core.paths decides.
_override: Path | None = None


def warehouse_path() -> Path:
    """The warehouse file the data layer reads."""
    return _override if _override is not None else paths.warehouse_path()


def warehouse_version() -> int:
    """The warehouse file's mtime in nanoseconds, 0 when it is missing. Part of
    every cache key, so a replaced file never answers from the cache."""
    try:
        return warehouse_path().stat().st_mtime_ns
    except FileNotFoundError:
        return 0


def warehouse_exists() -> bool:
    """Whether the warehouse file is there at all (app.py stops on False)."""
    return warehouse_path().exists()


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def _query(sql: str, params: tuple, path: str, version: int) -> pd.DataFrame:
    # version is only there to be part of the cache key.
    with duckdb.connect(path, read_only=True) as con:
        return con.execute(sql, list(params)).df()


def q(sql: str, params: tuple = ()) -> pd.DataFrame:
    """Run a read-only query and return a DataFrame (cached; see the module
    docstring)."""
    return _query(sql, tuple(params), str(warehouse_path()), warehouse_version())


# How many of the names are tables or views in the warehouse's own catalog.
# The names arrive as one list parameter.
_OBJECTS_SQL = """
    select count(distinct table_schema || '.' || table_name) as found
    from information_schema.tables
    where table_catalog = current_database()
      and list_contains(?, table_schema || '.' || table_name)
"""


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def _objects_exist(names: tuple[str, ...], path: str, version: int) -> bool:
    if version == 0:
        return False
    with duckdb.connect(path, read_only=True) as con:
        row = con.execute(_OBJECTS_SQL, [list(names)]).fetchone()
    return row is not None and row[0] == len(names)


def objects_exist(*names: str) -> bool:
    """Whether every schema-qualified table or view ("main.player_impact")
    is in the warehouse - for objects an older published warehouse may
    genuinely lack, so a page can show a notice instead of a catalog error.

    A missing warehouse file counts as missing objects. Anything else - a
    truncated download, a file that isn't a DuckDB database - raises: that
    is a broken warehouse, not an old one, and must not hide behind the
    notice. The catalog lookup itself can't raise a "does not exist" error,
    so there is nothing narrower to catch.
    """
    unique = tuple(sorted(set(names)))
    return _objects_exist(unique, str(warehouse_path()), warehouse_version())


def clear_caches() -> None:
    """Drop every cached result (q and objects_exist)."""
    _query.clear()
    _objects_exist.clear()


@contextmanager
def use_warehouse(path: Path) -> Iterator[Path]:
    """Point the data layer at `path` for the duration of the block, with the
    caches cleared on the way in and out. For tests; nests, and restores the
    previous location even when the block raises."""
    global _override
    previous = _override
    _override = Path(path)
    clear_caches()
    try:
        yield _override
    finally:
        _override = previous
        clear_caches()
