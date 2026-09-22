"""The feature matrix must contain nothing the model could not know before
tip-off, and must not silently lose games."""

import pytest

from ml.features import FEATURE_COLUMNS, build_feature_frame


@pytest.fixture(scope="module")
def frame(con):
    return build_feature_frame(con)


def test_every_feature_column_is_present(frame):
    missing = [c for c in FEATURE_COLUMNS if c not in frame.columns]
    assert not missing, f"missing feature columns: {missing}"


def test_targets_are_not_features():
    for target in ("margin", "home_won", "home_points", "away_points"):
        assert target not in FEATURE_COLUMNS, f"{target} leaks the result"


def test_one_row_per_game(frame, con):
    """One row per real game - real meaning excluding the one known
    no-contest fixture (a cancelled game recorded as a 0-0 final), which
    mart_game_features.sql deliberately drops via its valid_games CTE."""
    assert frame["game_id"].is_unique
    total = con.execute(
        """
        select count(*) from main_marts.fct_team_game
        where not (home_points = 0 and away_points = 0)
        """
    ).fetchone()[0]
    assert len(frame) == total


def test_first_game_of_a_season_has_no_prior_form(frame):
    """Opening night is the cold-start case the model must handle, so it has
    to be representable rather than dropped."""
    openers = frame[frame["home_games_played"] == 0]
    assert len(openers) > 0
    assert openers["home_season_margin"].isna().all()


def test_elo_is_populated_for_every_game(frame):
    assert frame["home_elo_pre"].notna().all()
    assert frame["away_elo_pre"].notna().all()
