"""Where the data lives. Every script, model and dashboard module resolves
the warehouse, the raw parquet folder and the version markers here, so a
change of location is one environment variable instead of a dozen edits.

  BIP_DATA_HOME   moves raw/ and warehouse/ under another folder
  BIP_WAREHOUSE   points at one warehouse file (wins over BIP_DATA_HOME for
                  the file; raw/ still follows BIP_DATA_HOME)

With neither set, everything is under the repo, exactly as before. A
relative value is read relative to the repo root, whatever the cwd.
Fixtures, run logs and the predictions history always stay in the repo: the
refresh commits the logs and the history.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# override=False: a real environment variable beats a line in .env.
load_dotenv(PROJECT_ROOT / ".env", override=False)


def _env_path(name: str) -> Path | None:
    # An empty value (BIP_DATA_HOME=) counts as unset.
    value = os.environ.get(name)
    if not value:
        return None
    # Relative values are anchored at the repo, not the cwd: dbt runs from
    # dbt/basketball_intelligence and the scripts from the root, and both
    # must land on the same file.
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def data_home() -> Path | None:
    """BIP_DATA_HOME, or None when it is not set."""
    return _env_path("BIP_DATA_HOME")


def raw_dir() -> Path:
    """Folder the ingestion scripts write parquet files to."""
    home = data_home()
    return home / "raw" if home else PROJECT_ROOT / "data" / "raw"


def warehouse_path() -> Path:
    """The DuckDB warehouse file."""
    override = _env_path("BIP_WAREHOUSE")
    if override:
        return override
    home = data_home()
    base = home if home else PROJECT_ROOT
    return base / "warehouse" / "basketball.duckdb"


def warehouse_version_path() -> Path:
    """Marker the dashboard writes beside a warehouse it downloaded."""
    return warehouse_path().with_suffix(".version")


def release_version_path() -> Path:
    """version.txt the refresh uploads next to the warehouse release asset."""
    return warehouse_path().parent / "version.txt"


def fixtures_dir() -> Path:
    """Small committed parquet files CI loads in place of the real data."""
    return PROJECT_ROOT / "data" / "fixtures"


def logs_dir() -> Path:
    """Run logs; they stay in the repo because the refresh commits them."""
    return PROJECT_ROOT / "logs"


def predictions_history_path() -> Path:
    """Every prediction ever issued, as a committed CSV. It is the source of
    truth the warehouse predictions table is rebuilt from, so it never moves
    with BIP_DATA_HOME."""
    return PROJECT_ROOT / "data" / "predictions" / "history.csv"


def team_codes_seed_path() -> Path:
    """The team_codes dbt seed. core.teams reads it directly, so ingestion
    (which runs before dbt) and the dashboard share dbt's facts without a
    warehouse; it is committed, so it never moves with BIP_DATA_HOME."""
    return PROJECT_ROOT / "dbt" / "basketball_intelligence" / "seeds" / "team_codes.csv"
