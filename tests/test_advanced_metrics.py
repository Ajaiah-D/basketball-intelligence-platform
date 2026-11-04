"""dashboard/lib/advanced_metrics.py: the metric tables the Advanced page
used to own, plus the minutes floor and percentile profile built on them."""

import pandas as pd

from dashboard.lib import advanced_metrics as am


def test_minutes_floor_scales_with_the_season():
    assert am.minutes_floor(pd.DataFrame({"minutes": [3000]})) == 500
    assert am.minutes_floor(pd.DataFrame({"minutes": [400]})) == 120
    assert am.minutes_floor(pd.DataFrame({"minutes": [100]})) == 50
    assert am.minutes_floor(pd.DataFrame({"minutes": []})) == 50


def test_advanced_percentiles_ranks_against_the_pool_and_skips_missing():
    pool = pd.DataFrame(
        {
            "true_shooting_pct": [50.0, 55.0, 60.0, 65.0],
            "usage_pct": [10.0, 20.0, 30.0, 40.0],
        }
    )
    row = pd.Series({"true_shooting_pct": 65.0, "usage_pct": float("nan")})
    out = am.advanced_percentiles(row, pool)
    labels = [r[0] for r in out]
    assert labels == ["TS%"]
    assert out[0][2] == 65.0
    assert out[0][1] > 50
