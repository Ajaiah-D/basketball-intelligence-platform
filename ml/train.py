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
#
# Refit from the RESIDUALS (margin - predicted_margin), not from the raw
# spread of margin itself. They are different numbers and the raw one is
# larger, so reaching for it makes calibration worse. Measured on the
# 2005-06 onward ridge backtest: residual SD 12.71, log-loss-optimal 11.24,
# Brier-optimal 11.23, against a raw target SD of 13.97. Moving this
# constant to 13.97 pushes log loss from 0.6113 up to 0.6121, while 11.24
# pulls it down to 0.6092. Accuracy and margin MAE do not depend on this
# constant at all; only the probability metrics move with it.
MARGIN_SD = 13.5

# Columns every result frame carries, including the empty one, so a caller
# can select on them without special-casing "no seasons qualified".
RESULT_COLUMNS = [
    "game_id", "season", "predicted_margin", "win_probability",
    "margin", "home_won",
]


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

    if not results:
        return pd.DataFrame(columns=RESULT_COLUMNS)
    return pd.concat(results, ignore_index=True)


# How to prove there is no leakage, for whoever extends this.
#
# A stable skill ratio across eras is NOT evidence that the features are
# clean, and must not be used as one. The tempting argument - "the model
# beats a mean-only baseline by the same ~10 percent in every era, so the
# error is dominated by irreducible variance and nothing is leaking" - does
# not hold. A proportional leak leaks more information in high-variance
# periods, so the ratio stays just as flat as it does on clean data.
# Measured counterexample: dropping "1 preceding" from the season window in
# mart_game_features.sql, the likeliest real bug in this pipeline, lifts
# accuracy to 0.718 and drops margin MAE to 9.15, tripping neither the 0.75
# accuracy gate nor the 8.0 MAE gate, while the pre/post-2019 skill ratio
# stays stable at 0.821 vs 0.829 against 0.895 vs 0.901 on clean data.
# Ratio stability rules out era-specific leakage only, not leakage.
#
# The standard that does work is structural re-derivation: recompute every
# rolling feature independently in pandas, groupby(season, team).shift(1)
# over a long frame built from fct_team_game, and diff it against the
# stored mart across the full population rather than a sample; then a
# causal test for the sequential features, flipping outcomes after a cutoff
# date and confirming no earlier game's Elo moves by any amount. Run on the
# current warehouse both come back at zero difference over all 52848 games,
# and the same comparison flags the leak above on 416068 values. Details in
# .superpowers/sdd/task-7-report.md.


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
