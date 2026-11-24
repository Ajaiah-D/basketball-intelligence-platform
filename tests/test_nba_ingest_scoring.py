"""The shot-location and play-type pulls in ingestion/nba_ingest.py, with the
API replaced: what each call asks for, how the answers are shaped, and
which seasons ask for them."""

import pandas as pd
import pytest

from ingestion import nba_ingest as ni


def test_season_gates():
    assert not ni.has_shot_locations("1995-96")
    assert ni.has_shot_locations("1996-97")
    assert not ni.has_play_types("2014-15")
    assert ni.has_play_types("2015-16")


def _play_type_rows(play_type: str) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "PLAYER_ID": [1, 1, 2],
            "TEAM_ABBREVIATION": ["AAA", "BBB", "AAA"],
            "PLAY_TYPE": [play_type] * 3,
            "TYPE_GROUPING": ["Offensive"] * 3,
            "POSS_PCT": [0.2, 0.1, 0.5],
            "POSS": [20, 10, 50],
        }
    )


def test_fetch_player_play_types_asks_once_per_play_type(monkeypatch):
    asked = []

    def fake(cls, **kw):
        asked.append(kw)
        return _play_type_rows(kw["play_type_nullable"])

    monkeypatch.setattr(ni, "call_endpoint", fake)
    df = ni.fetch_player_play_types("2024-25")

    assert [kw["play_type_nullable"] for kw in asked] == list(ni.PLAY_TYPES)
    for kw in asked:
        assert kw["season"] == "2024-25"
        assert kw["player_or_team_abbreviation"] == "P"
        assert kw["type_grouping_nullable"] == "offensive"
        assert kw["per_mode_simple"] == "Totals"
        assert kw["season_type_all_star"] == "Regular Season"
    # Every row of every answer is kept, a traded player's team rows too:
    # dbt adds them up.
    assert len(df) == 3 * len(ni.PLAY_TYPES)
    assert set(df["PLAY_TYPE"]) == set(ni.PLAY_TYPES)
    assert set(df["season"]) == {"2024-25"}


def test_fetch_player_play_types_skips_an_empty_answer(monkeypatch):
    def fake(cls, **kw):
        if kw["play_type_nullable"] == "Misc":
            return pd.DataFrame(columns=_play_type_rows("Misc").columns)
        return _play_type_rows(kw["play_type_nullable"])

    monkeypatch.setattr(ni, "call_endpoint", fake)
    df = ni.fetch_player_play_types("2024-25")
    assert "Misc" not in set(df["PLAY_TYPE"])
    assert len(df) == 3 * (len(ni.PLAY_TYPES) - 1)


def _shot_location_answer() -> pd.DataFrame:
    """The endpoint's real shape: two header rows, the zone over the stat,
    with an empty zone over the player columns."""
    columns = pd.MultiIndex.from_tuples(
        [
            ("", "PLAYER_ID"),
            ("", "PLAYER_NAME"),
            ("Restricted Area", "FGA"),
            ("In The Paint (Non-RA)", "FGA"),
            ("Mid-Range", "FGA"),
            ("Left Corner 3", "FGA"),
            ("Above the Break 3", "FGA"),
            ("Corner 3", "FGA"),
        ]
    )
    return pd.DataFrame([[1, "A", 10, 5, 3.0, None, 7, 2.0]], columns=columns)


def test_fetch_player_shot_locations_flattens_the_two_header_rows(monkeypatch):
    asked = []

    def fake(cls, **kw):
        asked.append(kw)
        return _shot_location_answer()

    monkeypatch.setattr(ni, "call_endpoint", fake)
    df = ni.fetch_player_shot_locations("2024-25")

    assert asked == [
        {
            "season": "2024-25",
            "distance_range": "By Zone",
            "per_mode_detailed": "Totals",
            "season_type_all_star": "Regular Season",
        }
    ]
    assert list(df.columns) == [
        "PLAYER_ID",
        "PLAYER_NAME",
        "RESTRICTED_AREA_FGA",
        "IN_THE_PAINT_NON_RA_FGA",
        "MID_RANGE_FGA",
        "LEFT_CORNER_3_FGA",
        "ABOVE_THE_BREAK_3_FGA",
        "CORNER_3_FGA",
        "season",
    ]
    assert df["RESTRICTED_AREA_FGA"].iloc[0] == 10
    assert set(df["season"]) == {"2024-25"}


@pytest.mark.parametrize("label, flat", [("Mid-Range", "MID_RANGE"), ("", "")])
def test_flat_zone_names(label, flat):
    assert ni.flat_zone(label) == flat


def test_run_fetches_shot_locations_and_play_types_only_for_their_seasons(tmp_path, monkeypatch):
    """Shot locations from 1996-97, play types from 2015-16."""
    monkeypatch.setattr(ni, "RAW_DIR", tmp_path)
    calls: list[tuple[str, str]] = []

    def frame(name, season=None):
        calls.append((name, season))
        return pd.DataFrame({"x": [1]})

    for fetcher in [
        "fetch_player_game_logs",
        "fetch_player_advanced",
        "fetch_team_advanced",
        "fetch_schedule",
        "fetch_players",
        "fetch_player_hustle",
        "fetch_player_on_off",
    ]:
        monkeypatch.setattr(ni, fetcher, lambda *a: pd.DataFrame({"x": [1]}))
    monkeypatch.setattr(
        ni, "fetch_team_game_logs", lambda s: pd.DataFrame({"GAME_DATE": ["d"], "GAME_ID": ["1"]})
    )
    monkeypatch.setattr(ni, "fetch_teams", lambda: pd.DataFrame({"x": [1]}))
    monkeypatch.setattr(ni, "fetch_player_defend", lambda s, c: pd.DataFrame({"x": [1]}))
    monkeypatch.setattr(
        ni, "fetch_player_bio", lambda s: pd.DataFrame({"PERSON_ID": [1], "TO_YEAR": [2016]})
    )
    monkeypatch.setattr(ni, "accumulate_birthdates", lambda bio, cap: None)
    monkeypatch.setattr(ni, "fetch_player_shot_locations", lambda s: frame("shots", s))
    monkeypatch.setattr(ni, "fetch_player_play_types", lambda s: frame("play_types", s))

    ni.run(["1995-96", "1996-97", "2014-15", "2015-16"], pbp_games=0)

    assert sorted(s for n, s in calls if n == "shots") == ["1996-97", "2014-15", "2015-16"]
    assert sorted(s for n, s in calls if n == "play_types") == ["2015-16"]
    assert (tmp_path / "player_shot_locations" / "1996-97.parquet").exists()
    assert (tmp_path / "player_play_types" / "2015-16.parquet").exists()


def test_the_new_season_files_are_shrink_guarded():
    assert "player_shot_locations" in ni.SHRINK_GUARDED
    assert "player_play_types" in ni.SHRINK_GUARDED
