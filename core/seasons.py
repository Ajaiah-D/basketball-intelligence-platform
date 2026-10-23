"""NBA season strings ("2025-26") from dates. Here rather than in the
ingester so the health check and anything else that only needs a date
rule doesn't pull in nba_api to get it."""

from __future__ import annotations

from datetime import date

from core.constants import SEASON_START_MONTH


def current_season(today: date | None = None) -> str:
    """NBA season string like '2025-26'. Seasons start in October
    (SEASON_START_MONTH); before October we are still in (or just finished)
    the season that began the prior year."""
    today = today or date.today()
    start_year = today.year if today.month >= SEASON_START_MONTH else today.year - 1
    return f"{start_year}-{str(start_year + 1)[-2:]}"


def season_range(start: str, end: str) -> list[str]:
    """All season strings from start to end inclusive, e.g. 1979-80..2025-26."""
    start_year, end_year = int(start[:4]), int(end[:4])
    return [f"{y}-{str(y + 1)[-2:]}" for y in range(start_year, end_year + 1)]
