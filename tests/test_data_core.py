"""dashboard/lib/data/core.py: where the data layer reads from, and its
caches - which must never serve one warehouse file's results for another,
or for an older copy of the same file."""

import os
from pathlib import Path

import duckdb
import pytest

from core import paths
from dashboard.lib.data import core


def _warehouse(path: Path, value: int) -> Path:
    """A one-table warehouse: main.t holds the single row `value`."""
    with duckdb.connect(str(path)) as con:
        con.execute("create or replace table t as select ? as x", [value])
    return path


def _bump_mtime(path: Path) -> None:
    """Move the file's mtime a second on: a rewrite inside one tick of the
    filesystem clock would otherwise look like the same version."""
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))


def test_the_default_path_is_core_paths():
    assert core.warehouse_path() == paths.warehouse_path()


def test_use_warehouse_points_at_a_file_and_restores_after(tmp_path):
    default = core.warehouse_path()
    a = _warehouse(tmp_path / "a.duckdb", 1)
    b = _warehouse(tmp_path / "b.duckdb", 2)
    with core.use_warehouse(a):
        assert core.warehouse_path() == a
        with core.use_warehouse(b):
            assert core.warehouse_path() == b
        assert core.warehouse_path() == a
    assert core.warehouse_path() == default


def test_use_warehouse_restores_after_an_exception(tmp_path):
    default = core.warehouse_path()
    with pytest.raises(RuntimeError), core.use_warehouse(tmp_path / "x.duckdb"):
        raise RuntimeError("boom")
    assert core.warehouse_path() == default


def test_version_is_zero_for_a_missing_file(tmp_path):
    with core.use_warehouse(tmp_path / "missing.duckdb"):
        assert core.warehouse_version() == 0
        assert core.warehouse_exists() is False


def test_version_is_the_file_mtime(tmp_path):
    path = _warehouse(tmp_path / "w.duckdb", 1)
    with core.use_warehouse(path):
        assert core.warehouse_exists() is True
        assert core.warehouse_version() == path.stat().st_mtime_ns


def test_q_runs_parameterised_sql(tmp_path):
    with core.use_warehouse(_warehouse(tmp_path / "w.duckdb", 7)):
        assert core.q("select x + ? as y from t", (1,))["y"].tolist() == [8]


def test_q_is_keyed_on_the_file(tmp_path):
    a = _warehouse(tmp_path / "a.duckdb", 1)
    b = _warehouse(tmp_path / "b.duckdb", 2)
    with core.use_warehouse(a):
        assert core.q("select x from t")["x"].tolist() == [1]
    with core.use_warehouse(b):
        assert core.q("select x from t")["x"].tolist() == [2]


def test_a_rewritten_file_is_not_served_from_the_cache(tmp_path):
    """The refresh swaps a new warehouse in under the same name: a cached
    result from the old file must not outlive it, with no explicit clear."""
    path = _warehouse(tmp_path / "w.duckdb", 1)
    with core.use_warehouse(path):
        assert core.q("select x from t")["x"].tolist() == [1]
        _warehouse(path, 2)
        _bump_mtime(path)
        assert core.q("select x from t")["x"].tolist() == [2]


def test_an_unchanged_file_is_served_from_the_cache(tmp_path):
    path = _warehouse(tmp_path / "w.duckdb", 1)
    with core.use_warehouse(path):
        version = core.warehouse_version()
        assert core.q("select x from t")["x"].tolist() == [1]
        _warehouse(path, 2)
        # Same version as the cached result: proves the cache is in use.
        os.utime(path, ns=(path.stat().st_atime_ns, version))
        assert core.q("select x from t")["x"].tolist() == [1]
        core.clear_caches()
        assert core.q("select x from t")["x"].tolist() == [2]


def test_objects_exist_checks_every_name(tmp_path):
    path = _warehouse(tmp_path / "w.duckdb", 1)
    with duckdb.connect(str(path)) as con:
        con.execute("create schema main_marts")
        con.execute("create view main_marts.v as select * from main.t")
    with core.use_warehouse(path):
        assert core.objects_exist("main.t") is True
        assert core.objects_exist("main.t", "main_marts.v") is True  # views count
        assert core.objects_exist("main.t", "main.missing") is False
        assert core.objects_exist("main_marts.t") is False  # schema matters


def test_objects_exist_sees_a_rewritten_file(tmp_path):
    path = _warehouse(tmp_path / "w.duckdb", 1)
    with core.use_warehouse(path):
        assert core.objects_exist("main.u") is False
        with duckdb.connect(str(path)) as con:
            con.execute("create table u as select 1 as y")
        _bump_mtime(path)
        assert core.objects_exist("main.u") is True


def test_objects_exist_is_false_without_a_warehouse(tmp_path):
    with core.use_warehouse(tmp_path / "missing.duckdb"):
        assert core.objects_exist("main.t") is False


def test_objects_exist_lets_a_broken_file_raise(tmp_path):
    """A truncated or corrupt download is a real error, not "the table isn't
    there yet": the page must not quietly hide behind its notice."""
    path = tmp_path / "broken.duckdb"
    path.write_bytes(b"not a duckdb file" * 100)
    with core.use_warehouse(path), pytest.raises(duckdb.Error):
        core.objects_exist("main.t")


def test_use_warehouse_clears_the_caches_on_entry_and_exit(tmp_path):
    """The file's mtime is pinned after every rewrite, so the cache key never
    changes: only use_warehouse's own clearing can make q() read it again."""
    path = _warehouse(tmp_path / "w.duckdb", 1)
    version = path.stat().st_mtime_ns

    def rewrite(value: int) -> None:
        _warehouse(path, value)
        os.utime(path, ns=(path.stat().st_atime_ns, version))

    def read() -> list[int]:
        return core.q("select x from t")["x"].tolist()

    with core.use_warehouse(path):
        assert read() == [1]
        rewrite(2)
        assert read() == [1]  # served from the cache
        with core.use_warehouse(path):
            assert read() == [2]  # entering cleared it
            rewrite(3)
            assert read() == [2]  # served from the cache
        assert read() == [3]  # leaving cleared it
