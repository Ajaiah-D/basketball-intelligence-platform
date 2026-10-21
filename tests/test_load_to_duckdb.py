"""load_to_duckdb replaces every raw table in one transaction: a parquet that
fails to load leaves the tables from the previous load in place."""

import sys
from pathlib import Path

import duckdb
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import load_to_duckdb


@pytest.fixture
def raw(tmp_path, monkeypatch):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    db = tmp_path / "warehouse" / "basketball.duckdb"
    monkeypatch.setattr(load_to_duckdb, "RAW_DIR", raw_dir)
    monkeypatch.setattr(load_to_duckdb, "DB_PATH", db)
    return raw_dir, db


def _rows(db: Path, table: str) -> list[tuple]:
    con = duckdb.connect(str(db), read_only=True)
    try:
        return con.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
    finally:
        con.close()


def test_loads_every_parquet_into_raw(raw):
    raw_dir, db = raw
    pd.DataFrame({"x": [1, 2]}).to_parquet(raw_dir / "a.parquet")
    pd.DataFrame({"y": [3]}).to_parquet(raw_dir / "b.parquet")
    load_to_duckdb.main()
    assert _rows(db, "raw.a") == [(1,), (2,)]
    assert _rows(db, "raw.b") == [(3,)]


def test_a_failed_load_rolls_back_every_table(raw):
    raw_dir, db = raw
    pd.DataFrame({"x": [1]}).to_parquet(raw_dir / "a.parquet")
    pd.DataFrame({"y": [1]}).to_parquet(raw_dir / "b.parquet")
    load_to_duckdb.main()

    # a.parquet loads first and would replace raw.a; b.parquet is corrupt
    pd.DataFrame({"x": [1, 2, 3]}).to_parquet(raw_dir / "a.parquet")
    (raw_dir / "b.parquet").write_bytes(b"not a parquet file")
    with pytest.raises(duckdb.Error):
        load_to_duckdb.main()

    assert _rows(db, "raw.a") == [(1,)]
    assert _rows(db, "raw.b") == [(1,)]
    # and the connection was closed: the file opens read-write again
    duckdb.connect(str(db)).close()
