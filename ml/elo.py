"""Sequential Elo ratings for NBA teams.

Elo cannot be a SQL window function: every game's update feeds the next
game's input. Ratings are emitted as they stood *before* each game, which
is the only form a pre-tipoff model may use.

Between seasons ratings regress toward 1500 to account for roster turnover.
The default carry of 0.75 is the common public choice; it is a tunable, not
a law.
"""

from __future__ import annotations

import pandas as pd

BASE_RATING = 1500.0


def expected_score(rating_a: float, rating_b: float) -> float:
    """Probability that A beats B, on the standard 400-point logistic scale."""
    return 1.0 / (1.0 + 10.0 ** ((rating_b - rating_a) / 400.0))


def compute_elo(
    games: pd.DataFrame,
    k: float = 20.0,
    home_advantage: float = 100.0,
    carry: float = 0.75,
) -> pd.DataFrame:
    """Pre-game Elo for every game, oldest first.

    `games` needs game_id, season, game_date, home_team_id, away_team_id and
    home_won. An optional is_neutral_site column (treated as all-False when
    the column is absent) suppresses the home-court term for that game -
    fct_team_game assigns a neutral game's "home" side by an arbitrary
    tiebreak (lower team_id), not a real home court, so applying +100 there
    would fabricate an advantage neither team has (confirmed real case:
    10 NBA Cup / international games in the current warehouse).

    `games` must already exclude no-contest fixtures before being passed
    in - a cancelled game recorded as a 0-0 final (confirmed instance:
    game_id 0021201214, 2013-04-16 IND @ BOS, postponed after the Boston
    Marathon bombing) is not a real result and would corrupt both teams'
    ratings around that date if included. The filter lives in the SQL that
    builds `games` (mart_game_features.sql's valid_games CTE and
    ml/features.py's matching query against fct_team_game), not here, since
    this function only sees home_won and has no access to the actual score.

    Returns game_id, home_elo_pre, away_elo_pre.
    """
    ordered = games.sort_values(["game_date", "game_id"])
    has_neutral_flag = "is_neutral_site" in ordered.columns
    ratings: dict[int, float] = {}
    current_season: str | None = None
    rows = []

    for game in ordered.itertuples(index=False):
        if game.season != current_season:
            # New season: pull every rating back toward the mean.
            ratings = {
                team: BASE_RATING + carry * (rating - BASE_RATING)
                for team, rating in ratings.items()
            }
            current_season = game.season

        home = ratings.get(game.home_team_id, BASE_RATING)
        away = ratings.get(game.away_team_id, BASE_RATING)
        rows.append((game.game_id, home, away))

        is_neutral = has_neutral_flag and bool(game.is_neutral_site)
        game_home_advantage = 0.0 if is_neutral else home_advantage
        expected_home = expected_score(home + game_home_advantage, away)
        actual_home = 1.0 if game.home_won else 0.0
        adjustment = k * (actual_home - expected_home)
        ratings[game.home_team_id] = home + adjustment
        ratings[game.away_team_id] = away - adjustment

    return pd.DataFrame(rows, columns=["game_id", "home_elo_pre", "away_elo_pre"])
