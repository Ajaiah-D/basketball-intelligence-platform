"""Walk-forward backtesting.

Random cross-validation on game data trains on the future to predict the
past and reports a score that cannot be reproduced live. This module only
ever trains on seasons strictly before the season being predicted, so every
number it reports is out of sample.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import norm
from sklearn.metrics import brier_score_loss, log_loss

from ml.features import FEATURE_COLUMNS

# Margin residuals are close to normal with a standard deviation near this.
# Turning a predicted margin into a win probability needs a spread; refit it
# from the residuals once a real model exists.
MARGIN_SD = 13.5


def margin_to_win_probability(margin, sd: float = MARGIN_SD) -> np.ndarray:
    """P(home wins) = P(margin > 0) under a normal centred on the prediction."""
    return norm.cdf(np.asarray(margin, dtype=float) / sd)


def walk_forward(
    frame: pd.DataFrame,
    model_factory,
    start_season: str,
    feature_columns: list[str] | None = None,
) -> pd.DataFrame:
    """Train on every prior season, predict the next, advance."""
    columns = feature_columns if feature_columns is not None else FEATURE_COLUMNS
    seasons = sorted(frame["season"].unique())
    results = []

    for season in [s for s in seasons if s >= start_season]:
        train = frame[frame["season"] < season]
        test = frame[frame["season"] == season]
        if train.empty or test.empty:
            continue

        X_train = train[columns].astype(float).fillna(0.0)
        X_test = test[columns].astype(float).fillna(0.0)
        model = model_factory().fit(X_train, train["margin"].astype(float))
        predicted = np.asarray(model.predict(X_test), dtype=float)

        results.append(pd.DataFrame({
            "game_id": test["game_id"].to_numpy(),
            "season": season,
            "predicted_margin": predicted,
            "win_probability": margin_to_win_probability(predicted),
            "margin": test["margin"].to_numpy(),
            "home_won": test["home_won"].to_numpy(),
        }))

    return pd.concat(results, ignore_index=True) if results else pd.DataFrame()


def evaluate(predictions: pd.DataFrame) -> dict:
    """Accuracy, calibration and margin error together.

    Accuracy alone hides a miscalibrated model: one that says 90% whenever
    it means 60% still looks fine on accuracy.
    """
    actual = predictions["home_won"].astype(bool).to_numpy()
    probability = predictions["win_probability"].astype(float).to_numpy()
    clipped = np.clip(probability, 1e-6, 1 - 1e-6)
    return {
        "accuracy": float(((probability > 0.5) == actual).mean()),
        "log_loss": float(log_loss(actual, clipped, labels=[False, True])),
        "brier": float(brier_score_loss(actual, clipped)),
        "margin_mae": float(np.abs(
            predictions["predicted_margin"].astype(float)
            - predictions["margin"].astype(float)).mean()),
        "n": int(len(predictions)),
    }
