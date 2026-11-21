"""The bio, birthdate, defender-tracking, hustle and on/off pulls in
ingestion/nba_ingest.py, with the API replaced: which seasons ask for what,
and how the birthdate cache grows."""

import pandas as pd

from ingestion import nba_ingest as ni


def _birthdate_answer(pid: int) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "PERSON_ID": [pid],
            "BIRTHDATE": ["2000-02-02T00:00:00"],
            "SCHOOL": ["Y"],
            "COUNTRY": ["USA"],
            "HEIGHT": ["6-6"],  # an extra column the cache must not keep
        }
    )


def test_season_gates():
    assert not ni.has_defense_tracking("2012-13")
    assert ni.has_defense_tracking("2013-14")
    assert not ni.has_hustle("2015-16")
    assert ni.has_hustle("2016-17")
    assert not ni.has_on_off("2006-07")
    assert ni.has_on_off("2007-08")


def test_accumulate_birthdates_fetches_only_missing_up_to_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(ni, "RAW_DIR", tmp_path)
    pd.DataFrame(
        {
            "PERSON_ID": [1],
            "BIRTHDATE": ["1990-01-01T00:00:00"],
            "SCHOOL": ["X"],
            "COUNTRY": ["USA"],
        }
    ).to_parquet(tmp_path / "player_birthdates.parquet")
    bio = pd.DataFrame({"PERSON_ID": [1, 2, 3, 4], "TO_YEAR": [2020, 2021, 1950, 2022]})
    asked = []

    def fake(cls, **kw):
        asked.append(kw["player_id"])
        return _birthdate_answer(kw["player_id"])

    monkeypatch.setattr(ni, "call_endpoint", fake)
    out = ni.accumulate_birthdates(bio, cap=1)
    # 1 is cached, 3's career ended before 1979, and the cap stops before 4.
    assert asked == [2]
    assert sorted(out["PERSON_ID"]) == [1, 2]
    assert list(out.columns) == ni.BIRTHDATE_COLS


def test_accumulate_birthdates_without_cap_fetches_all_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(ni, "RAW_DIR", tmp_path)
    monkeypatch.setattr(ni, "call_endpoint", lambda cls, **kw: _birthdate_answer(kw["player_id"]))
    bio = pd.DataFrame({"PERSON_ID": [7, 8], "TO_YEAR": ["2024", "2025"]})
    out = ni.accumulate_birthdates(bio, cap=None)
    assert sorted(out["PERSON_ID"]) == [7, 8]


def test_accumulate_birthdates_none_when_nothing_new(tmp_path, monkeypatch):
    monkeypatch.setattr(ni, "RAW_DIR", tmp_path)
    pd.DataFrame(
        {"PERSON_ID": [1], "BIRTHDATE": ["x"], "SCHOOL": [None], "COUNTRY": [None]}
    ).to_parquet(tmp_path / "player_birthdates.parquet")
    bio = pd.DataFrame({"PERSON_ID": [1], "TO_YEAR": [2020]})
    assert ni.accumulate_birthdates(bio, cap=None) is None


def test_failed_birthdate_is_skipped_not_fatal(tmp_path, monkeypatch):
    monkeypatch.setattr(ni, "RAW_DIR", tmp_path)

    def fake(cls, **kw):
        if kw["player_id"] == 5:
            raise KeyError("resultSet")
        return _birthdate_answer(kw["player_id"])

    monkeypatch.setattr(ni, "call_endpoint", fake)
    bio = pd.DataFrame({"PERSON_ID": [5, 6], "TO_YEAR": [2020, 2020]})
    out = ni.accumulate_birthdates(bio, cap=None)
    assert list(out["PERSON_ID"]) == [6]


def test_run_fetches_defense_only_for_tracked_seasons(tmp_path, monkeypatch):
    """A backfill asks for defender tracking from 2013-14 and hustle from
    2016-17, and the bio once per run."""
    monkeypatch.setattr(ni, "RAW_DIR", tmp_path)
    calls: list[tuple[str, str | None]] = []

    def frame(name, season=None):
        calls.append((name, season))
        df = pd.DataFrame({"x": [1]})
        return df

    monkeypatch.setattr(ni, "fetch_player_game_logs", lambda s: frame("pgl", s))
    monkeypatch.setattr(
        ni,
        "fetch_team_game_logs",
        lambda s: pd.DataFrame({"GAME_DATE": ["2020-01-01"], "GAME_ID": ["1"]}),
    )
    monkeypatch.setattr(ni, "fetch_player_advanced", lambda s: frame("padv", s))
    monkeypatch.setattr(ni, "fetch_team_advanced", lambda s: frame("tadv", s))
    monkeypatch.setattr(ni, "fetch_schedule", lambda s: frame("sched", s))
    monkeypatch.setattr(ni, "fetch_players", lambda s: frame("players", s))
    monkeypatch.setattr(ni, "fetch_teams", lambda: frame("teams"))
    monkeypatch.setattr(ni, "fetch_player_defend", lambda s, c: frame(f"defend:{c}", s))
    monkeypatch.setattr(ni, "fetch_player_hustle", lambda s: frame("hustle", s))
    monkeypatch.setattr(ni, "fetch_player_on_off", lambda s: frame("on_off", s))
    monkeypatch.setattr(
        ni,
        "fetch_player_bio",
        lambda s: pd.DataFrame({"PERSON_ID": [1], "TO_YEAR": [2016]}),
    )
    monkeypatch.setattr(ni, "accumulate_birthdates", lambda bio, cap: None)

    ni.run(["2006-07", "2007-08", "2012-13", "2013-14", "2016-17"], pbp_games=0)

    defend = sorted(s for n, s in calls if n == "defend:Overall")
    rim = sorted(s for n, s in calls if n == "defend:Less Than 6Ft")
    hustle = sorted(s for n, s in calls if n == "hustle")
    assert defend == rim == ["2013-14", "2016-17"]
    assert hustle == ["2016-17"]
    on_off = sorted(s for n, s in calls if n == "on_off")
    assert on_off == ["2007-08", "2012-13", "2013-14", "2016-17"]
    assert (tmp_path / "player_bio.parquet").exists()
    assert (tmp_path / "player_hustle" / "2016-17.parquet").exists()


def test_run_passes_the_birthdate_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(ni, "RAW_DIR", tmp_path)
    for name in [
        "fetch_player_game_logs",
        "fetch_player_advanced",
        "fetch_team_advanced",
        "fetch_schedule",
        "fetch_players",
        "fetch_player_hustle",
        "fetch_player_on_off",
    ]:
        monkeypatch.setattr(ni, name, lambda *a: pd.DataFrame({"x": [1]}))
    monkeypatch.setattr(
        ni, "fetch_team_game_logs", lambda s: pd.DataFrame({"GAME_DATE": ["d"], "GAME_ID": ["1"]})
    )
    monkeypatch.setattr(ni, "fetch_teams", lambda: pd.DataFrame({"x": [1]}))
    monkeypatch.setattr(ni, "fetch_player_defend", lambda s, c: pd.DataFrame({"x": [1]}))
    monkeypatch.setattr(
        ni, "fetch_player_bio", lambda s: pd.DataFrame({"PERSON_ID": [1], "TO_YEAR": [2024]})
    )
    caps = []
    monkeypatch.setattr(ni, "accumulate_birthdates", lambda bio, cap: caps.append(cap))

    ni.run(["2024-25"], pbp_games=0)
    ni.run(["2024-25"], pbp_games=0, birthdate_cap=None)
    ni.run(["2024-25"], pbp_games=0, birthdate_cap=0)
    assert caps == [ni.BIRTHDATE_MAX_NEW_PER_RUN, None]


def test_fetch_player_on_off_keeps_the_on_and_off_rows_of_every_team(monkeypatch):
    """One call per team; result set 0 (the team overall) is dropped and the
    on and off sets are kept with only ON_OFF_COLS."""
    monkeypatch.setattr(
        ni.static_teams, "get_teams", lambda: [{"id": 1, "abbreviation": "AAA"}, {"id": 2}]
    )
    asked = []

    def rows(team_id, status):
        return pd.DataFrame(
            {
                "GROUP_SET": ["On/Off Court"],
                "TEAM_ID": [team_id],
                "TEAM_ABBREVIATION": ["T"],
                "VS_PLAYER_ID": [10 + team_id],
                "VS_PLAYER_NAME": ["P"],
                "COURT_STATUS": [status],
                "GP": [5],
                "MIN": [100.0],
                "PLUS_MINUS": [1.0],
                "DEF_RATING": [110.0],
            }
        )

    def fake(cls, **kw):
        asked.append((kw["team_id"], kw["season"], kw["measure_type_detailed_defense"]))
        team = kw["team_id"]
        return [pd.DataFrame({"TEAM_ID": [team]}), rows(team, "On"), rows(team, "Off")]

    monkeypatch.setattr(ni, "call_endpoint_frames", fake)
    df = ni.fetch_player_on_off("2024-25")
    assert asked == [(1, "2024-25", "Advanced"), (2, "2024-25", "Advanced")]
    assert list(df.columns) == [*ni.ON_OFF_COLS, "season"]
    assert sorted(df["COURT_STATUS"]) == ["Off", "Off", "On", "On"]
    assert set(df["season"]) == {"2024-25"}
