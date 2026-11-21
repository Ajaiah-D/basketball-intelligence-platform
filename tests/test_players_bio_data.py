"""dashboard/lib/data/players.py's bio, position, age and defense readers,
against the warehouse (the fixture warehouse in CI) and against one without
the new marts."""

from dashboard.lib.data import players

LEBRON = 2544


def test_player_bio_has_the_index_fields(con):
    bio = players.player_bio(LEBRON)
    assert bio is not None
    assert bio["position"] == "F"
    assert bio["draft_year"] == 2003 and bio["draft_number"] == 1
    assert bio["height"] == "6-9"


def test_player_positions_one_row_per_player(con):
    positions = players.player_positions()
    assert len(positions) > 1000
    assert positions["player_id"].is_unique
    letters = set("".join(positions["position"]).replace("-", ""))
    assert letters <= {"G", "F", "C"}


def test_season_stats_carry_age(con):
    stats = players.player_season_stats("2024-25")
    lebron = stats[stats["player_id"] == LEBRON]
    assert int(lebron["age"].iloc[0]) == 40


def test_player_defense_has_tracking_columns(con):
    assert players.defense_available()
    df = players.player_defense("2024-25")
    row = df[df["player_id"] == LEBRON].iloc[0]
    for col in ("d_fg_pct_diff", "rim_fg_pct", "deflections_per_36", "steals_per_36"):
        assert row[col] == row[col], col  # not NaN
    history = players.player_defense_history(LEBRON)
    assert history["season"].is_monotonic_decreasing


def test_older_warehouse_has_no_bio_or_defense(tmp_warehouse_without_marts):
    assert not players.bio_available()
    assert players.player_bio(LEBRON) is None
    assert players.player_positions().empty
    assert not players.defense_available()
