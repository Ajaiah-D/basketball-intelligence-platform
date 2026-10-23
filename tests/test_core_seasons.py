"""core.seasons: the season a date falls in, and season ranges."""

from datetime import date

from core import seasons
from ingestion import nba_ingest


def test_the_season_rolls_over_on_october_1():
    assert seasons.current_season(date(2026, 9, 30)) == "2025-26"
    assert seasons.current_season(date(2026, 10, 1)) == "2026-27"
    assert seasons.current_season(date(2027, 1, 15)) == "2026-27"
    assert seasons.current_season(date(1999, 12, 31)) == "1999-00"


def test_season_range_is_inclusive():
    assert seasons.season_range("1998-99", "2001-02") == [
        "1998-99",
        "1999-00",
        "2000-01",
        "2001-02",
    ]
    assert seasons.season_range("2025-26", "2025-26") == ["2025-26"]


def test_the_ingester_uses_the_core_functions():
    # Its CLI default and --backfill go through these names.
    assert nba_ingest.current_season is seasons.current_season
    assert nba_ingest.season_range is seasons.season_range
