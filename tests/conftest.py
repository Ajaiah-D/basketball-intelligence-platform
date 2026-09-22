"""Shared fixtures. Tests run read-only against the real warehouse and
assert facts that are true of the data itself, not row counts that shift
on every refresh."""

import os
import sys
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DB_PATH = ROOT / "warehouse" / "basketball.duckdb"


@pytest.fixture(scope="session")
def con():
    if not DB_PATH.exists():
        # Locally a missing warehouse is a normal state - a developer who
        # has not run the pipeline yet - so skipping is right. In CI it is
        # a failure of the fixture-load step, and skipping there would let
        # the run go green while silently testing almost nothing: every
        # test behind this fixture (test_db_metrics.py's true-shooting era
        # guards, test_features.py's leakage checks) would skip, the ~19
        # synthetic-data tests would still pass, and pytest would exit 0.
        # GitHub Actions sets CI=true automatically.
        if os.environ.get("CI"):
            pytest.fail("warehouse missing in CI - the fixture load step did not run")
        pytest.skip("warehouse not built; run scripts/load_to_duckdb.py")
    connection = duckdb.connect(str(DB_PATH), read_only=True)
    yield connection
    connection.close()
