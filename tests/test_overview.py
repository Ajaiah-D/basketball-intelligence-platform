import pandas as pd

from dashboard.views import overview


def _stats(gp_max: int) -> pd.DataFrame:
    return pd.DataFrame({
        "player": ["Volume Shooter", "Three For Three", "Solid"],
        "gp": [gp_max, 3, gp_max],
        "fg3_pct": [41.0, 100.0, 38.0],
        "tpa_total": [500, 3, 300],
    })


def test_shooting_leaders_need_real_volume():
    """A bench player who went 3-for-3 must not top a 3P% leaderboard."""
    leaders, floor = overview.shooting_leaders(_stats(82), "fg3_pct", "tpa_total", 100)
    assert floor == 100
    assert leaders["player"].tolist() == ["Volume Shooter", "Solid"]


def test_shooting_floor_scales_with_the_season_so_far():
    """Ten games into a season nobody has 100 threes yet; the cut scales."""
    _, floor = overview.shooting_leaders(_stats(10), "fg3_pct", "tpa_total", 100)
    assert floor == 12  # 100 * 10/82, rounded
