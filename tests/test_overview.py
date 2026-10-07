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


def test_points_per_game_is_one_teams_average_not_both_combined():
    """The KPI used to add home and away scores and show ~231 under a label
    every fan reads as one team's points per game (~115)."""
    games = pd.DataFrame({"home_pts": [120, 110], "away_pts": [100, 130]})
    assert overview.team_points_per_game(games) == 115.0
    assert overview.team_points_per_game(games.iloc[0:0]) is None
