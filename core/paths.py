"""Where the data lives. Every script, model and dashboard module resolves
the warehouse, the raw parquet folder and the version markers here, so a
change of location is one environment variable instead of a dozen edits.

  BIP_DATA_HOME   moves raw/ and warehouse/ under another folder
  BIP_WAREHOUSE   points at one warehouse file (wins over BIP_DATA_HOME for
                  the file; raw/ still follows BIP_DATA_HOME)

With neither set, everything is under the repo, exactly as before.
Fixtures and run logs always stay in the repo: the refresh commits the logs.
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
    return Path(value) if value else None


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
