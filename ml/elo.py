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


def _regress_toward_mean(ratings: dict[int, float], carry: float) -> dict[int, float]:
    """Pull every rating back toward BASE_RATING - the between-season step,
    shared by compute_elo and current_ratings so they cannot drift apart."""
    return {
        team: BASE_RATING + carry * (rating - BASE_RATING)
        for team, rating in ratings.items()
    }


def _apply_game(
    ratings: dict[int, float],
    game,
    k: float,
    home_advantage: float,
    has_neutral_flag: bool,
) -> tuple[float, float]:
    """Update `ratings` in place for one game. Returns the PRE-game
    (home, away) ratings - the values compute_elo's per-row output needs -
    so the two functions share this single update step instead of each
    reimplementing it."""
    home = ratings.get(game.home_team_id, BASE_RATING)
    away = ratings.get(game.away_team_id, BASE_RATING)

    is_neutral = has_neutral_flag and bool(game.is_neutral_site)
    game_home_advantage = 0.0 if is_neutral else home_advantage
    expected_home = expected_score(home + game_home_advantage, away)
    actual_home = 1.0 if game.home_won else 0.0
    adjustment = k * (actual_home - expected_home)
    ratings[game.home_team_id] = home + adjustment
    ratings[game.away_team_id] = away - adjustment
    return home, away


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

    Callers converting these ratings to a win probability must add
    home_advantage themselves, and must suppress it for is_neutral_site
    games, exactly as this function does internally.

    Returns game_id, home_elo_pre, away_elo_pre. Note this is PRE-game -
    a team's rating entering a game, not its rating after one. A caller
    that wants a team's actual current rating (e.g. to predict a game that
    hasn't been played yet) wants current_ratings() below, not the last row
    of this output - see that function's docstring for why the two differ.
    """
    ordered = games.sort_values(["game_date", "game_id"])
    has_neutral_flag = "is_neutral_site" in ordered.columns
    ratings: dict[int, float] = {}
    current_season: str | None = None
    rows = []

    for game in ordered.itertuples(index=False):
        if game.season != current_season:
            ratings = _regress_toward_mean(ratings, carry)
            current_season = game.season

        home_pre, away_pre = _apply_game(ratings, game, k, home_advantage, has_neutral_flag)
        rows.append((game.game_id, home_pre, away_pre))

    return pd.DataFrame(rows, columns=["game_id", "home_elo_pre", "away_elo_pre"])


def current_ratings(
    games: pd.DataFrame,
    as_of_season: str,
    k: float = 20.0,
    home_advantage: float = 100.0,
    carry: float = 0.75,
) -> dict:
    """Each team's rating right now: the state after every game in `games`,
    with the between-season regression applied if `as_of_season` is a
    season not yet represented in `games`.

    compute_elo's own regression only fires when it processes a game row
    FROM the new season - if zero games of that season have been played
    yet (e.g. predicting opening night), the regression never runs and a
    caller reading compute_elo's last per-game output gets last season's
    raw rating, unregressed. This function runs the identical update loop
    (via the same _regress_toward_mean/_apply_game helpers compute_elo
    uses, so the two can never silently diverge in their update math) but
    returns the final internal state directly, and applies one more
    regression step at the end if as_of_season is genuinely new.

    This also gives the correct POST-game rating, unlike reading the last
    row of compute_elo's output: compute_elo only ever returns the rating a
    team held ENTERING each game, so the last row for a team is off by that
    one game's own adjustment from its actual current rating.
    """
    ordered = games.sort_values(["game_date", "game_id"])
    has_neutral_flag = "is_neutral_site" in ordered.columns
    ratings: dict[int, float] = {}
    current_season: str | None = None

    for game in ordered.itertuples(index=False):
        if game.season != current_season:
            ratings = _regress_toward_mean(ratings, carry)
            current_season = game.season
        _apply_game(ratings, game, k, home_advantage, has_neutral_flag)

    if current_season is not None and current_season != as_of_season:
        ratings = _regress_toward_mean(ratings, carry)

    return ratings
