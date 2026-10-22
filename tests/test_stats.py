"""dashboard/lib/stats.py: leaderboard qualification and percentile ranks."""

import pandas as pd
import pytest

from dashboard.lib.stats import percentile_of, qualification_threshold


@pytest.mark.parametrize(
    ("max_gp", "expected"),
    [(82, 25), (30, 18), (10, 6), (1, 1)],
)
def test_qualification_scales_with_the_season_and_caps_at_full(max_gp, expected):
    assert qualification_threshold(pd.DataFrame({"gp": [1, max_gp]})) == expected


def test_qualification_of_an_empty_season_is_zero():
    assert qualification_threshold(pd.DataFrame({"gp": []})) == 0


def test_percentile_counts_values_strictly_below():
    series = pd.Series([10.0, 20.0, 30.0, None, 40.0])  # the null is ignored
    assert percentile_of(series, 30.0) == 50.0
    assert percentile_of(series, 30.0, higher_is_better=False) == 50.0
    assert percentile_of(series, 45.0) == 100.0
    assert percentile_of(series, 45.0, higher_is_better=False) == 0.0


@pytest.mark.parametrize("value", [float("nan")])
def test_percentile_of_a_missing_value_is_none(value):
    assert percentile_of(pd.Series([1.0, 2.0]), value) is None


def test_percentile_against_an_empty_pool_is_none():
    assert percentile_of(pd.Series([], dtype=float), 1.0) is None
