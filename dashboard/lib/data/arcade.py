"""The Arcade's data: the player-season pool Higher or Lower and Mystery
Player draw from, and the team builder's impact tables."""

from __future__ import annotations

import pandas as pd

from .core import objects_exist, q

# The first season with complete box scores, where the impact pool and the
# team builder's all-time opponents start. (Task 14 moves this to
# core/constants.py.)
COMPLETE_BOX_SCORE_FIRST_SEASON = "1985-86"


def arcade_pool(min_gp: int = 50, min_ppg: float = 14.0) -> pd.DataFrame:
    """Notable player-seasons across every ingested season - the pool both
    guessing games draw from. One row per player per season, with the
    player's age that season where known (null otherwise)."""
    return q(
        """
        select
            season,
            player_id,
            player_name           as player,
            team,
            games_played          as gp,
            points_per_game       as ppg,
            rebounds_per_game     as rpg,
            assists_per_game      as apg,
            steals_per_game       as spg,
            blocks_per_game       as bpg,
            threes_made_per_game  as tpg,
            three_pa_per_game     as tpa_pg,
            fg_pct,
            fg3_pct,
            ft_pct,
            age
        from main_marts.mart_player_season
        where games_played >= ? and points_per_game >= ?
        order by season, player_id
        """,
        (min_gp, min_ppg),
    )


def player_impact_available() -> bool:
    """Whether the team builder's tables exist - a warehouse published before
    ml/player_impact.py first ran has neither."""
    return objects_exist("main.player_impact", "main.player_impact_meta")


def player_impact_pool(season: str | None) -> pd.DataFrame:
    """The team builder's pool: one season's player-seasons, or every season
    when `season` is None, best impact first."""
    if season is None:
        return q(
            """
            select season, player_id, player, team, gp, mpg, ppg, rpg, apg,
                   impact, usage, cost
            from main.player_impact
            order by impact desc, player_id, season
            """
        )
    return q(
        """
        select season, player_id, player, team, gp, mpg, ppg, rpg, apg,
               impact, usage, cost
        from main.player_impact
        where season = ?
        order by impact desc, player_id
        """,
        (season,),
    )


def player_impact_meta() -> dict:
    """The impact model's single metadata row (calibration, league usage
    total, fit quality) as a dict; empty if the table has no row."""
    df = q("select * from main.player_impact_meta limit 1")
    return df.iloc[0].to_dict() if len(df) else {}


def all_team_net_ratings() -> pd.DataFrame:
    """Every team-season's net rating from 1985-86 on (season, team,
    net_rating), oldest first. The Arcade's all-time Build mode draws its
    opponents from these; 1985-86 is where the impact pool starts too."""
    return q(
        """
        select season, team_abbreviation as team, net_rating
        from main_marts.mart_team_season
        where season >= ? and net_rating is not null
        order by season, team_abbreviation
        """,
        (COMPLETE_BOX_SCORE_FIRST_SEASON,),
    )
