"""Team-season standings and one team's game log.

A team's conference is a column of mart_team_standings, joined there from
the team_codes seed; Python code that needs one without a standings row
asks core.teams.conference(), which reads the same seed.
"""

from __future__ import annotations

import pandas as pd

from .core import q


def standings(season: str) -> pd.DataFrame:
    """Standings for one season: record, scoring splits, conference and the
    last-five form string, ordered for playoff seeding.

    The order is dbt's mart_team_standings: win percentage, then a
    (simplified - see the model's comment) head-to-head tiebreak, then point
    differential, then the abbreviation so a re-run can't reshuffle a tie.
    """
    return q(
        """
        select
            team_id,
            team_abbreviation   as team,
            team_name,
            games_played        as gp,
            wins                as w,
            losses              as l,
            win_pct             as pct,
            points_per_game     as ppg,
            opp_points_per_game as opp_ppg,
            net_points          as net,
            conference          as conf,
            form
        from main_marts.mart_team_standings
        where season = ?
        order by win_pct desc, head_to_head desc, net_points desc, team_abbreviation asc
        """,
        (season,),
    )


def team_game_log(team_id: int, season: str) -> pd.DataFrame:
    """One team's games in a season, oldest first, each with the opponent and
    its score - what the Teams page's splits and margins chart read."""
    return q(
        """
        select
            game_id,
            game_date,
            matchup,
            is_away_game,
            is_win,
            points,
            opp_points,
            opp_team_abbreviation as opponent
        from main_intermediate.int_team_game_opponent
        where team_id = ? and season = ?
        order by game_date, game_id
        """,
        (team_id, season),
    )
