"""Single games: the season's results, and one game's play-by-play and box
score."""

from __future__ import annotations

import pandas as pd

from .core import q


def games_list(season: str) -> pd.DataFrame:
    """Every game of a season, newest first, oriented home versus away.

    Reads fct_team_game, the one place that decides which side is home: the
    predictions grade against it too, so a neutral-site game (both teams
    listed as away) gets the same home team on the Games page as on the
    Predictions page.
    """
    return q(
        """
        select
            game_id,
            game_date,
            away_team_abbreviation as away,
            away_points            as away_pts,
            home_team_abbreviation as home,
            home_points            as home_pts
        from main_marts.fct_team_game
        where season = ?
        order by game_date desc, game_id
        """,
        (season,),
    )


def pbp_game_ids() -> set[str]:
    """The games that have play-by-play ingested."""
    return set(q("select distinct game_id from main_staging.stg_play_by_play")["game_id"])


def game_pbp(game_id: str) -> pd.DataFrame:
    """One game's play-by-play in game order: what the game-flow and shot
    charts draw. action_number repeats within a game now and then, so
    action_id breaks the tie."""
    return q(
        """
        select
            game_id,
            action_number,
            action_id,
            period,
            game_clock,
            team_tricode,
            player_name,
            action_type,
            description,
            is_field_goal,
            shot_result,
            shot_distance_ft,
            shot_x,
            shot_y,
            score_home,
            score_away
        from main_staging.stg_play_by_play
        where game_id = ?
        order by action_number, action_id
        """,
        (game_id,),
    )


def game_box_score(game_id: str) -> pd.DataFrame:
    """One game's box score, both teams, most minutes first."""
    return q(
        """
        select
            team_abbreviation        as team,
            team_id,
            player_name              as player,
            minutes_played           as min,
            points                   as pts,
            total_rebounds           as reb,
            assists                  as ast,
            steals                   as stl,
            blocks                   as blk,
            turnovers                as tov,
            field_goals_made         as fgm,
            field_goals_attempted    as fga,
            three_pointers_made      as tpm,
            three_pointers_attempted as tpa,
            free_throws_made         as ftm,
            free_throws_attempted    as fta,
            plus_minus
        from main_staging.stg_player_game_logs
        where game_id = ?
        order by minutes_played desc, points desc, player_id
        """,
        (game_id,),
    )
