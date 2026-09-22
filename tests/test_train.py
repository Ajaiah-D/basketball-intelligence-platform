"""The harness must train only on the past. These tests are the reason the
backtest can be believed, so they assert the split itself, not the score."""

import numpy as np
import pandas as pd
import pytest

from ml.train import evaluate, walk_forward


class SpyModel:
    """Records the size of each training set so the split can be asserted."""

    seen: list = []

    def fit(self, X, y):
        SpyModel.seen.append(len(X))
        return self

    def predict(self, X):
        return np.zeros(len(X))


def _frame():
    margins = np.linspace(-20, 20, 30)
    return pd.DataFrame({
        "game_id": [str(i) for i in range(30)],
        "season": ["2000-01"] * 10 + ["2001-02"] * 10 + ["2002-03"] * 10,
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


def test_every_prediction_is_out_of_sample():
    out = walk_forward(_frame(), SpyModel, start_season="2001-02",
                       feature_columns=["elo_diff"])
    assert set(out["season"]) == {"2001-02", "2002-03"}
    assert len(out) == 20


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
