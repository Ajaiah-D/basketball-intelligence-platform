"""load_to_duckdb replaces every raw table in one transaction: a parquet that
fails to load leaves the tables from the previous load in place. It also
rebuilds the predictions table from the committed history CSV."""

import sys
from datetime import datetime
from pathlib import Path

import duckdb
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ml.predict import CREATE_TABLE, PREDICTION_COLUMNS, append_history, stamp_predictions
from scripts import load_to_duckdb


@pytest.fixture
def raw(tmp_path, monkeypatch):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    db = tmp_path / "warehouse" / "basketball.duckdb"
    monkeypatch.setattr(load_to_duckdb, "RAW_DIR", raw_dir)
    monkeypatch.setattr(load_to_duckdb, "DB_PATH", db)
    # No history unless a test writes one: the committed CSV stays out of it.
    monkeypatch.setattr(load_to_duckdb, "PREDICTIONS_CSV", tmp_path / "history.csv")
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


# -- the predictions history ----------------------------------------------------


def _history(path: Path, game_ids: tuple[str, ...], at: str) -> pd.DataFrame:
    n = len(game_ids)
    rows = pd.DataFrame(
        {
            "game_id": list(game_ids),
            "season": ["2026-27"] * n,
            "game_date": pd.to_datetime(["2026-10-21"] * n).date,
            "home_team_id": [1610612738] * n,
            "away_team_id": [1610612747] * n,
            "predicted_margin": [1 / 3] * n,
            "win_probability": [0.6123456789012345] * n,
        }
    )
    stamped = stamp_predictions(rows, now=datetime.fromisoformat(at))
    append_history(stamped, path)
    return stamped


def _schema(db: Path) -> list[tuple]:
    con = duckdb.connect(str(db), read_only=True)
    try:
        return con.execute(
            "select column_name, data_type from information_schema.columns "
            "where table_schema = 'main' and table_name = 'predictions' "
            "order by ordinal_position"
        ).fetchall()
    finally:
        con.close()


def test_predictions_are_rebuilt_from_the_history(raw, tmp_path):
    raw_dir, db = raw
    pd.DataFrame({"x": [1]}).to_parquet(raw_dir / "a.parquet")
    csv = tmp_path / "history.csv"
    first = _history(csv, ("0022600001", "0022600002"), "2026-10-13 10:03:17.803463")
    second = _history(csv, ("0022600001",), "2026-10-20 10:00:00")
    load_to_duckdb.main()

    # the same table, column for column, that ml.predict creates
    reference = duckdb.connect(":memory:")
    reference.execute(CREATE_TABLE)
    expected_schema = reference.execute(
        "select column_name, data_type from information_schema.columns "
        "where table_name = 'predictions' order by ordinal_position"
    ).fetchall()
    assert _schema(db) == expected_schema

    con = duckdb.connect(str(db), read_only=True)
    try:
        loaded = con.execute("select * from predictions order by predicted_at, game_id").df()
    finally:
        con.close()
    expected = pd.concat([first, second], ignore_index=True)
    assert list(loaded.columns) == list(PREDICTION_COLUMNS)
    assert list(loaded["prediction_id"]) == list(expected["prediction_id"])
    assert list(loaded["game_id"]) == ["0022600001", "0022600002", "0022600001"]
    # floats and timestamps survive the CSV exactly
    assert list(loaded["predicted_margin"]) == [1 / 3] * 3
    assert list(loaded["win_probability"]) == [0.6123456789012345] * 3
    assert loaded["predicted_at"].iloc[0] == pd.Timestamp("2026-10-13 10:03:17.803463")


def test_the_history_replaces_whatever_predictions_table_was_there(raw, tmp_path):
    raw_dir, db = raw
    pd.DataFrame({"x": [1]}).to_parquet(raw_dir / "a.parquet")
    db.parent.mkdir(parents=True)
    con = duckdb.connect(str(db))
    con.execute(CREATE_TABLE)
    con.execute("insert into predictions (prediction_id) values ('stale')")
    con.close()
    _history(tmp_path / "history.csv", ("0022600001",), "2026-10-20 10:00:00")
    load_to_duckdb.main()
    ids = [r[0] for r in _rows(db, "predictions")]
    assert "stale" not in ids
    assert len(ids) == 1


def test_an_empty_history_gives_an_empty_table(raw, tmp_path):
    raw_dir, db = raw
    pd.DataFrame({"x": [1]}).to_parquet(raw_dir / "a.parquet")
    (tmp_path / "history.csv").write_text(",".join(PREDICTION_COLUMNS) + "\n")
    load_to_duckdb.main()
    assert _rows(db, "predictions") == []
    assert [c for c, _ in _schema(db)] == list(PREDICTION_COLUMNS)


def test_without_a_history_the_predictions_table_is_left_alone(raw):
    raw_dir, db = raw
    pd.DataFrame({"x": [1]}).to_parquet(raw_dir / "a.parquet")
    db.parent.mkdir(parents=True)
    con = duckdb.connect(str(db))
    con.execute(CREATE_TABLE)
    con.execute("insert into predictions (prediction_id) values ('kept')")
    con.close()
    load_to_duckdb.main()
    assert [r[0] for r in _rows(db, "predictions")] == ["kept"]


def test_a_bad_history_rolls_back_the_raw_tables_too(raw, tmp_path):
    raw_dir, db = raw
    pd.DataFrame({"x": [1]}).to_parquet(raw_dir / "a.parquet")
    load_to_duckdb.main()
    pd.DataFrame({"x": [1, 2]}).to_parquet(raw_dir / "a.parquet")
    (tmp_path / "history.csv").write_text("game_id,win_probability\n1,0.5\n")
    with pytest.raises(ValueError, match="header"):
        load_to_duckdb.main()
    assert _rows(db, "raw.a") == [(1,)]
