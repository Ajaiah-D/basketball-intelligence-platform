"""Assemble the model matrix: the dbt feature mart joined to Elo."""

from __future__ import annotations

import pandas as pd

from ml.elo import compute_elo

FEATURE_COLUMNS = [
    "home_elo_pre", "away_elo_pre", "elo_diff",
    "home_season_margin", "away_season_margin",
    "home_season_win_pct", "away_season_win_pct",
    "home_last5_margin", "away_last5_margin",
    "home_last10_margin", "away_last10_margin",
    "home_days_rest", "away_days_rest",
    "home_back_to_back", "away_back_to_back",
    "home_games_played", "away_games_played",
    "is_neutral_site",
]


def build_feature_frame(con) -> pd.DataFrame:
    """One row per game: features, plus margin and home_won as targets."""
    features = con.execute(
        "select * from main_marts.mart_game_features order by game_date, game_id"
    ).df()
    # Same no-contest exclusion as mart_game_features.sql's valid_games CTE
    # (a cancelled game recorded as a 0-0 final must not feed Elo either),
    # and is_neutral_site is included so compute_elo can suppress the
    # home-court term for the games fct_team_game flagged as neutral.
    games = con.execute(
        """
        select game_id, season, game_date, home_team_id, away_team_id,
               home_won, is_neutral_site
        from main_marts.fct_team_game
        where not (home_points = 0 and away_points = 0)
        order by game_date, game_id
        """
    ).df()
    elo = compute_elo(games)
    merged = features.merge(elo, on="game_id", how="left")
    merged["elo_diff"] = merged["home_elo_pre"] - merged["away_elo_pre"]
    for column in ("home_days_rest", "away_days_rest"):
        merged[column] = pd.to_numeric(merged[column], errors="coerce")
    return merged
