"""Advanced metrics: dbt's player-season and team-season marts.

These two read the whole mart row (`select *`) on purpose. The mart's
columns are the documented interface (_marts_models.yml), the Players page
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


def similarity_pool(season: str) -> pd.DataFrame:
    """player_advanced(season) plus the columns lib.similarity needs that
    the season mart doesn't hold: threes_per_36, height_inches (the bio
    mart) and fouls_per_36, rim_share, contests_per_36 and
    deflections_per_36 (the defense mart). rim_share is the share of the
    shots he defended that came at the rim. A warehouse published before
    the bio or defense mart gets those columns as nulls, and the model
    leaves them out."""
    has_bio = objects_exist("main_marts.mart_player_bio")
    has_defense = objects_exist("main_marts.mart_player_defense")
    bio = "b.height_inches" if has_bio else "null::double"
    defense = (
        """d.fouls_per_36,
            d.rim_fga / nullif(d.d_fga, 0)  as rim_share,
            d.contested_per_36              as contests_per_36,
            d.deflections_per_36"""
        if has_defense
        else """null::double as fouls_per_36,
            null::double as rim_share,
            null::double as contests_per_36,
            null::double as deflections_per_36"""
    )
    joins = ""
    if has_bio:
        joins += " left join main_marts.mart_player_bio b on b.player_id = s.player_id"
    if has_defense:
        joins += (
            " left join main_marts.mart_player_defense d"
            " on d.season = s.season and d.player_id = s.player_id"
        )
    return q(
        f"""
        select
            s.*,
            36.0 * s.tpa_total / nullif(s.minutes, 0)  as threes_per_36,
            {bio} as height_inches,
            {defense}
        from main_marts.mart_player_season s{joins}
        where s.season = ?
        order by s.player_id
        """,
        (season,),
    )


def player_advanced_history(player_id: int) -> pd.DataFrame:
    """Every season of one player's advanced metrics, newest first (the
    whole mart row, as player_advanced)."""
    return q(
        """
        select *
        from main_marts.mart_player_season
        where player_id = ?
        order by season desc
        """,
        (player_id,),
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
