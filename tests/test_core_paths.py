"""core.paths: one place that decides where the warehouse, raw files and
logs live. The functions read the environment on every call, so these tests
steer them with monkeypatch.setenv."""

from pathlib import Path

import pytest

from core import paths

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv("BIP_DATA_HOME", raising=False)
    monkeypatch.delenv("BIP_WAREHOUSE", raising=False)


def test_project_root_is_the_repo_root():
    assert paths.PROJECT_ROOT == ROOT


def test_defaults_with_no_env():
    assert paths.data_home() is None
    assert paths.raw_dir() == ROOT / "data" / "raw"
    assert paths.warehouse_path() == ROOT / "warehouse" / "basketball.duckdb"
    assert paths.warehouse_version_path() == ROOT / "warehouse" / "basketball.version"
    assert paths.release_version_path() == ROOT / "warehouse" / "version.txt"
    assert paths.fixtures_dir() == ROOT / "data" / "fixtures"
    assert paths.logs_dir() == ROOT / "logs"


def test_data_home_moves_raw_and_the_warehouse(monkeypatch, tmp_path):
    monkeypatch.setenv("BIP_DATA_HOME", str(tmp_path))
    assert paths.data_home() == tmp_path
    assert paths.raw_dir() == tmp_path / "raw"
    assert paths.warehouse_path() == tmp_path / "warehouse" / "basketball.duckdb"
    assert paths.warehouse_version_path() == tmp_path / "warehouse" / "basketball.version"
    assert paths.release_version_path() == tmp_path / "warehouse" / "version.txt"


def test_data_home_leaves_fixtures_and_logs_in_the_repo(monkeypatch, tmp_path):
    # Fixtures and run logs are committed, so they never follow the data.
    monkeypatch.setenv("BIP_DATA_HOME", str(tmp_path))
    assert paths.fixtures_dir() == ROOT / "data" / "fixtures"
    assert paths.logs_dir() == ROOT / "logs"


def test_warehouse_env_overrides_the_file_only(monkeypatch, tmp_path):
    copy = tmp_path / "copy" / "build.duckdb"
    monkeypatch.setenv("BIP_WAREHOUSE", str(copy))
    assert paths.warehouse_path() == copy
    assert paths.raw_dir() == ROOT / "data" / "raw"
    assert paths.data_home() is None


def test_warehouse_env_beats_data_home(monkeypatch, tmp_path):
    copy = tmp_path / "elsewhere" / "build.duckdb"
    monkeypatch.setenv("BIP_DATA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("BIP_WAREHOUSE", str(copy))
    assert paths.warehouse_path() == copy
    assert paths.raw_dir() == tmp_path / "home" / "raw"


def test_version_paths_follow_the_warehouse_file(monkeypatch, tmp_path):
    copy = tmp_path / "copy" / "build.duckdb"
    monkeypatch.setenv("BIP_WAREHOUSE", str(copy))
    # The downloaded-version marker sits beside the file, named for it; the
    # release marker is always version.txt in the same folder.
    assert paths.warehouse_version_path() == tmp_path / "copy" / "build.version"
    assert paths.release_version_path() == tmp_path / "copy" / "version.txt"


def test_empty_env_values_count_as_unset(monkeypatch):
    monkeypatch.setenv("BIP_DATA_HOME", "")
    monkeypatch.setenv("BIP_WAREHOUSE", "")
    assert paths.data_home() is None
    assert paths.warehouse_path() == ROOT / "warehouse" / "basketball.duckdb"
