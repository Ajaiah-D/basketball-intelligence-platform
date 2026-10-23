"""The seasons in the warehouse - what the sidebar's season picker offers."""

from __future__ import annotations

from .core import q


def seasons() -> list[str]:
    """All ingested seasons, newest first."""
    df = q("select distinct season from main_staging.stg_team_game_logs order by season desc")
    return df["season"].tolist()


def latest_season() -> str:
    """The newest ingested season."""
    return seasons()[0]
