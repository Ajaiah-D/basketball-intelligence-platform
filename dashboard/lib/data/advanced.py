"""Advanced metrics: dbt's player-season and team-season marts.

These two read the whole mart row (`select *`) on purpose. The mart's
columns are the documented interface (_marts_models.yml), the Advanced page
picks its columns from a table of metrics, and the Teams page checks for
optional ones (`"effective_fg_pct" in adv`) - a written-out list would turn
that check into a binder error on a warehouse published before a column
existed.
"""

from __future__ import annotations

import pandas as pd

from .core import objects_exist, q


def marts_available() -> bool:
    """Whether the advanced marts are in the warehouse - a warehouse where
    dbt has not run has neither, and the pages show a notice instead."""
    return objects_exist("main_marts.mart_player_season", "main_marts.mart_team_season")


def player_advanced(season: str, min_minutes: int = 0) -> pd.DataFrame:
    """Advanced metrics for one season. Rate stats are meaningless on tiny
    samples (one made three is a 150% TS%), so callers pass a minutes floor."""
    return q(
        """
        select *
        from main_marts.mart_player_season
        where season = ? and minutes >= ?
        order by player_id
        """,
        (season, min_minutes),
    )


def team_advanced(season: str) -> pd.DataFrame:
    """Every team's ratings, Four Factors and pace for one season, best net
    rating first."""
    return q(
        """
        select *
        from main_marts.mart_team_season
        where season = ?
        order by net_rating desc nulls last, team_abbreviation
        """,
        (season,),
    )


def advanced_seasons() -> list[str]:
    """Seasons where the box score is complete enough for advanced metrics
    (1985-86 on), newest first. Earlier seasons are missing whole columns at
    the source."""
    return q(
        """
        select distinct season
        from main_marts.mart_player_season
        where box_score_complete
        order by season desc
        """
    )["season"].tolist()
