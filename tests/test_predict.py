"""Predictions are the public record. The properties that make that record
credible - written before tip-off, never rewritten - are asserted here."""

from datetime import datetime

import duckdb
import pandas as pd
import pytest

from core import io as core_io
from ml import predict
from ml.predict import (
    MODEL_VERSION,
    PREDICTION_COLUMNS,
    append_history,
    stamp_predictions,
    write_predictions,
)

HEADER = ",".join(PREDICTION_COLUMNS) + "\n"


@pytest.fixture
def memory_db():
    con = duckdb.connect(":memory:")
    con.execute("""
        create table predictions (
            prediction_id varchar, model_version varchar,
            predicted_at timestamp, game_id varchar, season varchar,
            game_date date, home_team_id bigint, away_team_id bigint,
            predicted_margin double, win_probability double
        )
    """)
    return con


def _rows(game_ids=("0022600001",)):
    n = len(game_ids)
    return pd.DataFrame(
        {
            "game_id": list(game_ids),
            "season": ["2026-27"] * n,
            "game_date": pd.to_datetime(["2026-10-20"] * n).date,
            "home_team_id": [1610612738] * n,
            "away_team_id": [1610612747] * n,
            "predicted_margin": [3.5] * n,
            "win_probability": [0.61] * n,
        }
    )


def _stamped(game_ids=("0022600001",), at="2026-10-20 10:02:42.804615"):
    return stamp_predictions(_rows(game_ids), now=datetime.fromisoformat(at))


def test_writing_twice_appends_rather_than_overwrites(memory_db):
    write_predictions(memory_db, stamp_predictions(_rows()))
    write_predictions(memory_db, stamp_predictions(_rows()))
    total = memory_db.execute("select count(*) from predictions").fetchone()[0]
    assert total == 2, "a re-run must not erase the earlier prediction"


def test_every_row_carries_the_model_version(memory_db):
    write_predictions(memory_db, stamp_predictions(_rows()))
    versions = memory_db.execute("select distinct model_version from predictions").fetchall()
    assert versions == [(MODEL_VERSION,)]


def test_win_probability_stays_a_probability(memory_db):
    write_predictions(memory_db, stamp_predictions(_rows()))
    bad = memory_db.execute(
        "select count(*) from predictions where win_probability not between 0 and 1"
    ).fetchone()[0]
    assert bad == 0


def test_stamped_rows_have_exactly_the_table_columns(memory_db):
    stamped = _stamped()
    assert list(stamped.columns) == list(PREDICTION_COLUMNS)
    table = [r[0] for r in memory_db.execute("describe predictions").fetchall()]
    assert table == list(PREDICTION_COLUMNS)


# -- the committed history CSV --------------------------------------------------


def test_append_history_creates_the_file_with_a_header(tmp_path):
    path = tmp_path / "predictions" / "history.csv"
    assert append_history(_stamped(), path) == 1
    lines = path.read_bytes().decode().splitlines(keepends=True)
    assert lines[0] == HEADER
    assert len(lines) == 2


def test_append_history_is_append_only(tmp_path):
    path = tmp_path / "history.csv"
    append_history(_stamped(("0022600001", "0022600002")), path)
    before = path.read_bytes()
    append_history(_stamped(("0022600001",), at="2026-10-27 10:00:00.000001"), path)
    after = path.read_bytes()
    # every byte already in the file stays exactly where it was
    assert after.startswith(before)
    assert len(after.decode().splitlines()) == 4


def test_a_game_can_be_predicted_again_by_a_later_run(tmp_path):
    # The table keeps every run's prediction for a game (ml.evaluate grades
    # the earliest, the page shows the latest), so the history must too.
    path = tmp_path / "history.csv"
    append_history(_stamped(at="2026-10-13 10:00:00"), path)
    append_history(_stamped(at="2026-10-20 10:00:00"), path)
    history = pd.read_csv(path, dtype=str)
    assert list(history["game_id"]) == ["0022600001", "0022600001"]


def test_no_duplicate_per_game_model_version_and_run(tmp_path):
    path = tmp_path / "history.csv"
    stamped = _stamped(("0022600001", "0022600002"))
    append_history(stamped, path)
    before = path.read_bytes()
    # The same run's rows again (a retried step): nothing is added, even with
    # fresh prediction_ids.
    again = stamped.copy()
    again["prediction_id"] = ["x", "y"]
    assert append_history(again, path) == 0
    assert path.read_bytes() == before


def test_a_batch_with_a_duplicate_key_is_refused(tmp_path):
    path = tmp_path / "history.csv"
    with pytest.raises(ValueError, match="duplicate"):
        append_history(_stamped(("0022600001", "0022600001")), path)
    assert not path.exists()


def test_rows_are_ordered_by_creation_time_then_game_id(tmp_path):
    path = tmp_path / "history.csv"
    early = _stamped(("0022600009", "0022600002"), at="2026-10-13 10:00:00")
    late = _stamped(("0022600001",), at="2026-10-14 10:00:00")
    append_history(pd.concat([late, early]), path)
    history = pd.read_csv(path, dtype=str)
    assert list(history["game_id"]) == ["0022600002", "0022600009", "0022600001"]


def test_a_batch_older_than_the_history_is_refused(tmp_path):
    # Appending it would break the creation-time order, and reordering past
    # rows is exactly what the file must never do.
    path = tmp_path / "history.csv"
    append_history(_stamped(at="2026-10-20 10:00:00"), path)
    before = path.read_bytes()
    with pytest.raises(ValueError, match="older") as refused:
        append_history(_stamped(("0022600002",), at="2026-10-19 10:00:00"), path)
    assert path.read_bytes() == before
    # the message says what to do about it
    assert "system clock" in str(refused.value)
    assert "last row" in str(refused.value)


def test_an_aware_predicted_at_is_written_as_naive_utc(tmp_path):
    path = tmp_path / "history.csv"
    stamped = _stamped()
    stamped["predicted_at"] = [pd.Timestamp("2026-10-20 12:00:00+02:00")]
    append_history(stamped, path)
    row = path.read_bytes().decode().splitlines()[1].split(",")
    assert dict(zip(PREDICTION_COLUMNS, row, strict=True))["predicted_at"] == (
        "2026-10-20 10:00:00.000000"
    )


def test_formats_are_fixed(tmp_path):
    path = tmp_path / "history.csv"
    stamped = _stamped(at="2026-10-20 10:00:00")
    stamped["predicted_margin"] = [1 / 3]
    append_history(stamped, path)
    row = path.read_bytes().decode().splitlines()[1].split(",")
    record = dict(zip(PREDICTION_COLUMNS, row, strict=True))
    # microseconds always written, even when zero
    assert record["predicted_at"] == "2026-10-20 10:00:00.000000"
    assert record["game_date"] == "2026-10-20"
    assert record["game_id"] == "0022600001"
    assert record["home_team_id"] == "1610612738"
    # shortest repr that round-trips: no precision lost, no float noise added
    assert record["predicted_margin"] == repr(1 / 3)
    assert float(record["predicted_margin"]) == 1 / 3
    assert record["win_probability"] == "0.61"


def test_rewriting_what_was_read_back_is_byte_identical(tmp_path):
    first = tmp_path / "first.csv"
    stamped = pd.concat(
        [
            _stamped(("0022600001", "0022600002"), at="2026-10-13 10:03:17.803463"),
            _stamped(("0022600001",), at="2026-10-20 10:02:42"),
        ]
    )
    stamped["predicted_margin"] = [3.284092013, -0.1, 6.195837]
    append_history(stamped, first)
    # read it the way the loader does, write it again: same bytes
    con = duckdb.connect(":memory:")
    reread = con.execute(predict.read_history_sql(), [str(first)]).df()
    second = tmp_path / "second.csv"
    append_history(reread, second)
    assert second.read_bytes() == first.read_bytes()


def test_appends_keep_the_file_s_own_line_endings(tmp_path):
    # A Windows checkout with core.autocrlf may hand us CRLF; mixing endings
    # would turn every append into a whole-file diff.
    path = tmp_path / "history.csv"
    append_history(_stamped(at="2026-10-13 10:00:00"), path)
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    append_history(_stamped(at="2026-10-20 10:00:00"), path)
    data = path.read_bytes()
    assert data.count(b"\r\n") == 3
    assert data.count(b"\n") == 3


def test_a_file_with_the_wrong_header_is_refused(tmp_path):
    path = tmp_path / "history.csv"
    path.write_text("game_id,win_probability\n")
    with pytest.raises(ValueError, match="header"):
        append_history(_stamped(), path)
    assert path.read_text() == "game_id,win_probability\n"


def test_an_empty_batch_writes_nothing(tmp_path):
    path = tmp_path / "history.csv"
    assert append_history(_stamped().iloc[0:0], path) == 0
    assert not path.exists()


def test_a_failed_write_leaves_the_history_untouched(tmp_path, monkeypatch):
    path = tmp_path / "history.csv"
    append_history(_stamped(at="2026-10-13 10:00:00"), path)
    before = path.read_bytes()

    def broken_replace(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(core_io.os, "replace", broken_replace)
    with pytest.raises(OSError, match="disk full"):
        append_history(_stamped(at="2026-10-20 10:00:00"), path)
    assert path.read_bytes() == before
    assert list(tmp_path.iterdir()) == [path]


# -- main(): the CSV and the warehouse table in one run -------------------------


@pytest.fixture
def run_main(tmp_path, monkeypatch):
    """main() against a temp warehouse and history, with the model faked."""
    warehouse = tmp_path / "basketball.duckdb"
    history = tmp_path / "data" / "predictions" / "history.csv"
    monkeypatch.setenv("BIP_WAREHOUSE", str(warehouse))
    monkeypatch.delenv(predict.DRY_RUN_ENV, raising=False)
    monkeypatch.setattr(predict.paths, "predictions_history_path", lambda: history)
    batch = _stamped(("0022600001", "0022600002"))

    def go(rows=batch):
        monkeypatch.setattr(predict, "fit_and_predict", lambda con, through=None: rows)
        predict.main()
        con = duckdb.connect(str(warehouse), read_only=True)
        try:
            ids = con.execute("select prediction_id from predictions order by game_id").fetchall()
        except duckdb.CatalogException:
            ids = []
        finally:
            con.close()
        return [i[0] for i in ids]

    return {"go": go, "history": history, "batch": batch}


def test_main_appends_to_the_history_and_the_table(run_main):
    table_ids = run_main["go"]()
    history = pd.read_csv(run_main["history"], dtype=str)
    assert sorted(history["prediction_id"]) == sorted(table_ids)
    assert len(table_ids) == 2


def test_a_dry_run_writes_the_table_but_not_the_history(run_main, monkeypatch):
    monkeypatch.setenv(predict.DRY_RUN_ENV, "1")
    assert len(run_main["go"]()) == 2
    assert not run_main["history"].exists()


def test_a_refused_append_fails_the_step_with_its_reason(run_main, caplog):
    # A history whose last row is newer than this run (a clock gone back):
    # main exits non-zero, the reason is its last log line - which is what
    # the refresh records as the predict step's error - and the table is
    # not written either.
    newer = _stamped(("0022600009",), at="2030-01-01 00:00:00")
    append_history(newer, run_main["history"])
    with pytest.raises(SystemExit) as exit_info:
        run_main["go"]()
    assert exit_info.value.code == 1
    assert "system clock" in caplog.records[-1].getMessage()
    assert caplog.records[-1].levelname == "ERROR"


def test_an_empty_slate_writes_nothing(run_main):
    assert run_main["go"](run_main["batch"].iloc[0:0]) == []
    assert not run_main["history"].exists()
