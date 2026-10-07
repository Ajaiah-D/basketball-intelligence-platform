import pandas as pd

from dashboard.lib import glossary
from dashboard.views import overview


def test_ast_to_leaders_need_real_playmaking_volume():
    """A center with 40 assists and 8 turnovers has a 5.0 ratio and no
    business leading a playmaking list; the per-game floor keeps him off."""
    stats = pd.DataFrame({
        "player": ["Point Guard", "Low-Usage Big", "Wing"],
        "apg": [9.0, 0.6, 4.0],
        "ast_to": [4.1, 5.0, 2.2],
    })
    leaders = overview.ast_to_leaders(stats)
    assert leaders["player"].tolist() == ["Point Guard", "Wing"]


def test_close_game_share_counts_five_points_or_fewer():
    games = pd.DataFrame({"home_pts": [100, 110, 99, 120],
                          "away_pts": [105, 104, 100, 90]})
    # margins 5, 6, 1, 30 -> two of four within five
    assert overview.close_game_share(games) == 0.5
    assert overview.close_game_share(games.iloc[0:0]) is None


def test_best_record_spotlight_names_the_team_and_record(monkeypatch):
    monkeypatch.setattr(overview.media, "team_logo_data_uri", lambda team_id: None)
    standings = pd.DataFrame({"team_id": [1610612765], "team": ["DET"],
                              "team_name": ["Detroit Pistons"], "w": [60], "l": [22]})
    html = overview.best_record_spot(standings)
    assert "Best record" in html
    assert "Detroit Pistons" in html and "60-22" in html
    assert overview.best_record_spot(standings.iloc[0:0]) == ""


def test_new_terms_are_explained():
    assert "turnover" in glossary.TERMS["AST/TO"].lower()
    assert "5 points" in glossary.TERMS["Close games"]
