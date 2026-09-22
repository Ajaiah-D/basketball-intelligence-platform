"""The harness must train only on the past. These tests are the reason the
backtest can be believed, so they assert the split itself, not the score."""

import numpy as np
import pandas as pd
import pytest

from ml.train import evaluate, walk_forward

# Row order of the fixture below, kept module level so the spy can name the
# season each training row came from. Asserting sizes alone would pass a
# split that swapped rows between seasons while keeping the counts right.
SEASON_BY_ROW = ["2000-01"] * 10 + ["2001-02"] * 10 + ["2002-03"] * 10


class SpyModel:
    """Records the size and the season content of each training set."""

    seen: list = []
    seasons: list = []

    def fit(self, X, y):
        SpyModel.seen.append(len(X))
        SpyModel.seasons.append(sorted({SEASON_BY_ROW[i] for i in X.index}))
        return self

    def predict(self, X):
        return np.zeros(len(X))


@pytest.fixture(autouse=True)
def _reset_spy():
    SpyModel.seen = []
    SpyModel.seasons = []


def _frame():
    margins = np.linspace(-20, 20, 30)
    return pd.DataFrame({
        "game_id": [str(i) for i in range(30)],
        "season": SEASON_BY_ROW,
        "elo_diff": np.linspace(-100, 100, 30),
        "margin": margins,
        "home_won": margins > 0,
    })


def test_training_set_grows_and_never_includes_the_test_season():
    SpyModel.seen = []
    walk_forward(_frame(), SpyModel, start_season="2001-02",
                 feature_columns=["elo_diff"])
    # Predicting 2001-02 trains on the 10 games of 2000-01; predicting
    # 2002-03 trains on 20. Never on its own season.
    assert SpyModel.seen == [10, 20]
    # And those rows really are the earlier seasons, not merely the right
    # number of rows: a swap that kept the counts would pass the line above.
    assert SpyModel.seasons == [["2000-01"], ["2000-01", "2001-02"]]


def test_every_prediction_is_out_of_sample():
    out = walk_forward(_frame(), SpyModel, start_season="2001-02",
                       feature_columns=["elo_diff"])
    assert set(out["season"]) == {"2001-02", "2002-03"}
    assert len(out) == 20


def test_the_earliest_season_is_skipped_not_trained_on_itself():
    """start_season at the very first season is the one case where a season
    could train on itself. It must be skipped for want of any prior data."""
    out = walk_forward(_frame(), SpyModel, start_season="2000-01",
                       feature_columns=["elo_diff"])
    assert SpyModel.seen == [10, 20]
    assert SpyModel.seasons == [["2000-01"], ["2000-01", "2001-02"]]
    # 2000-01 has no earlier season to learn from, so it is never predicted.
    assert set(out["season"]) == {"2001-02", "2002-03"}
    assert len(out) == 20


def test_no_qualifying_season_still_returns_the_documented_columns():
    """An empty result keeps its schema, so a caller can select on it
    instead of hitting a KeyError on a frame with no columns at all."""
    out = walk_forward(_frame(), SpyModel, start_season="2099-00",
                       feature_columns=["elo_diff"])
    assert len(out) == 0
    assert SpyModel.seen == []
    assert list(out.columns) == ["game_id", "season", "predicted_margin",
                                 "win_probability", "margin", "home_won"]


def test_evaluate_reports_the_metrics_that_matter():
    out = pd.DataFrame({
        "win_probability": [0.9, 0.1, 0.6, 0.4],
        "home_won": [True, False, True, False],
        "predicted_margin": [10.0, -10.0, 2.0, -2.0],
        "margin": [8.0, -12.0, 1.0, -3.0],
    })
    metrics = evaluate(out)
    assert metrics["accuracy"] == pytest.approx(1.0)
    assert metrics["margin_mae"] == pytest.approx(1.5)
    assert 0 < metrics["brier"] < 0.1
    assert metrics["n"] == 4
