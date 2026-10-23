"""dashboard/lib/data/diagnosis.py: the rotation behind a team's profile,
its league medians, and the player rows the scatter reads.

Two warehouses: a tiny synthetic one where every number is known (a
traded player, a player one game short of the rotation, an unqualified
outlier the medians must ignore), and the real one for named facts."""

import duckdb
import pandas as pd
import pytest

from dashboard.lib import diagnosis as D
from dashboard.lib.data import core as data_core
from dashboard.lib.data import diagnosis

SEASON = "2030-31"

# (player_id, name, team_label, qualified, true_shooting_pct, fg3_pct season)
PLAYERS = [
    (1, "Ann Alpha", "AAA", True, 60.0, 40.0),
    (2, "Bob Beta", "BBB → AAA", True, 55.0, 30.0),
    (3, "Cid Gamma", "AAA", False, 58.0, 38.0),
    (4, "Dee Delta", "BBB", True, 50.0, 35.0),
    (5, "Eve Outlier", "BBB", False, 99.0, 99.0),
]

# (player_id, team_id, team, games, tpa_total, three_pa_per_game, fg3_pct)
STINTS = [
    (1, 10, "AAA", 20, 100, 5.0, 41.0),
    (2, 20, "BBB", 30, 50, 1.7, 26.0),
    (2, 10, "AAA", 12, 60, 5.0, 35.0),
    (3, 10, "AAA", 9, 40, 4.4, 20.0),
    (4, 20, "BBB", 40, 80, 2.0, 35.0),
    (5, 20, "BBB", 3, 5, 1.7, 99.0),
]

# (player_id, team_id, team, minutes) - two log rows each, to be summed
LOGS = [
    (1, 10, "AAA", 300),
    (1, 10, "AAA", 340),
    (2, 20, "BBB", 500),
    (2, 10, "AAA", 200),
    (2, 10, "AAA", 150),
    (3, 10, "AAA", 90),
]


def _table(con, name, df):
    con.register("df_view", df)
    con.execute(f"create table {name} as select * from df_view")
    con.unregister("df_view")


@pytest.fixture
def diagnosis_warehouse(tmp_path):
    path = tmp_path / "diagnosis.duckdb"
    con = duckdb.connect(str(path))
    con.execute("create schema main_marts")
    con.execute("create schema main_staging")
    season_rows = []
    pct_rows = []
    defense_rows = []
    for pid, name, label, qualified, ts, fg3 in PLAYERS:
        season_rows.append(
            {
                "season": SEASON,
                "player_id": pid,
                "player_name": name,
                "team": label[-3:],
                "team_label": label,
                "games_played": 20 + pid,
                "minutes_per_game": 30.0,
                "points_per_game": 10.0 + pid,
                "rebounds_per_game": 5.0,
                "assists_per_game": 3.0,
                "steals_per_game": 1.0,
                "blocks_per_game": 0.5,
                "threes_made_per_game": 1.5,
                "three_pa_per_game": 4.0,
                "fg3_pct": fg3,
                "true_shooting_pct": ts,
                "effective_fg_pct": ts - 3,
                "usage_pct": 20.0,
                "assist_pct": 15.0,
                "rebound_pct": 10.0,
                "turnover_pct": 10.0 + pid,
                "offensive_rebound_pct": 5.0,
                "defensive_rebound_pct": 15.0,
                "steal_pct": 1.5,
                "block_pct": 1.0,
                "three_point_attempt_rate": 0.4,
                "free_throw_rate": 0.25,
                "plus_minus_per_game": 1.0,
                "player_impact_estimate": 10.0,
                "game_score": 9.0,
            }
        )
        pct = {"season": SEASON, "player_id": pid, "is_qualified": qualified}
        for col in D.driver_measures():
            pct[f"{col}_pctile"] = 50.0 if qualified else None
        pct_rows.append(pct)
        defense_rows.append(
            {
                "season": SEASON,
                "player_id": pid,
                "on_court_def_rating": 110.0,
                "est_off_court_def_rating": 112.0 if pid == 1 else None,
                "def_on_minus_off": -2.0 if pid == 1 else None,
                "fouls_per_36": 2.0 + pid / 10,
            }
        )
    _table(con, "main_marts.mart_player_season", pd.DataFrame(season_rows))
    _table(con, "main_marts.mart_player_percentiles", pd.DataFrame(pct_rows))
    _table(con, "main_marts.mart_player_defense", pd.DataFrame(defense_rows))
    names = {p[0]: p[1] for p in PLAYERS}
    _table(
        con,
        "main_marts.mart_player_team_season",
        pd.DataFrame(
            [
                {
                    "season": SEASON,
                    "player_id": pid,
                    "player_name": names[pid],
                    "team_id": tid,
                    "team_abbreviation": team,
                    "games_played": gp,
                    "minutes_per_game": 30.0,
                    "three_pa_per_game": tpa_pg,
                    "tpa_total": tpa,
                    "fg3_pct": fg3,
                }
                for pid, tid, team, gp, tpa, tpa_pg, fg3 in STINTS
            ]
        ),
    )
    _table(
        con,
        "main_staging.stg_player_game_logs",
        pd.DataFrame(
            [
                {
                    "season": SEASON,
                    "player_id": pid,
                    "team_id": tid,
                    "team_abbreviation": team,
                    "minutes_played": minutes,
                }
                for pid, tid, team, minutes in LOGS
            ]
        ),
    )
    _table(
        con,
        "main_marts.mart_team_profile",
        pd.DataFrame(
            [
                {"season": SEASON, "team_abbreviation": t, "pace": p, "pace_rank": r}
                for t, p, r in (("BBB", 99.0, 2), ("AAA", 101.0, 1))
            ]
        ),
    )
    con.close()
    with data_core.use_warehouse(path):
        yield path


# --- Synthetic warehouse ---------------------------------------------------------


def test_profile_is_available_only_with_all_three_marts(diagnosis_warehouse):
    assert diagnosis.profile_available()
    with duckdb.connect(str(diagnosis_warehouse)) as con:
        con.execute("drop table main_marts.mart_player_defense")
    data_core.clear_caches()
    assert not diagnosis.profile_available()


def test_profile_is_unavailable_on_an_old_warehouse(tmp_warehouse_without_marts):
    assert not diagnosis.profile_available()


def test_team_profile_is_the_season_by_team(diagnosis_warehouse):
    profile = diagnosis.team_profile(SEASON)
    assert profile["team_abbreviation"].tolist() == ["AAA", "BBB"]
    assert diagnosis.team_profile("1999-00").empty


def test_the_rotation_is_ten_games_for_this_team(diagnosis_warehouse):
    rows = diagnosis.team_drivers(SEASON, "AAA")
    # Cid Gamma played 9 games; Bob Beta's 30 BBB games don't count here.
    assert rows["player"].tolist() == ["Ann Alpha", "Bob Beta"]
    assert rows["games_played"].tolist() == [20, 12]
    assert rows["minutes"].tolist() == [640, 350]


def test_three_point_share_is_of_the_teams_attempts(diagnosis_warehouse):
    rows = diagnosis.team_drivers(SEASON, "AAA").set_index("player")
    # AAA took 100 + 60 + 40 = 200 threes, Cid Gamma's 40 included.
    assert rows.loc["Ann Alpha", "team_three_pa_share"] == pytest.approx(0.5)
    assert rows.loc["Bob Beta", "team_three_pa_share"] == pytest.approx(0.3)
    # Bob's 3P% is his AAA stint, his true shooting his whole season.
    assert rows.loc["Bob Beta", "fg3_pct"] == pytest.approx(35.0)
    assert rows.loc["Bob Beta", "true_shooting_pct"] == pytest.approx(55.0)
    assert rows.loc["Bob Beta", "team_label"] == "BBB → AAA"


def test_league_medians_are_over_qualified_players_only(diagnosis_warehouse):
    rows = diagnosis.team_drivers(SEASON, "AAA")
    # Qualified: Ann 60, Bob 55, Dee 50. With Cid (58) and Eve (99), who
    # are not, the medians would be 58 and 38.
    assert set(rows["true_shooting_pct_league_median"]) == {55.0}
    assert set(rows["fg3_pct_league_median"]) == {35.0}
    # Only Ann has an on/off estimate.
    assert set(rows["def_on_minus_off_league_median"]) == {-2.0}


def test_drivers_carry_every_area_measure_and_its_median(diagnosis_warehouse):
    rows = diagnosis.team_drivers(SEASON, "AAA")
    expected = {
        "player_id",
        "player",
        "games_played",
        "minutes",
        "minutes_per_game",
        "three_pa_per_game",
        "fg3_pct",
        "team_three_pa_share",
    }
    for col in D.driver_measures():
        expected |= {col, f"{col}_league_median"}
    assert expected <= set(rows.columns)


def test_an_unknown_team_has_no_rotation(diagnosis_warehouse):
    assert diagnosis.team_drivers(SEASON, "ZZZ").empty


def test_player_percentiles_row_or_none(diagnosis_warehouse):
    row = diagnosis.player_percentiles(SEASON, 1)
    assert row is not None and bool(row["is_qualified"])
    assert diagnosis.player_percentiles(SEASON, 999) is None


def test_league_player_rows_filter_on_games(diagnosis_warehouse):
    rows = diagnosis.league_player_rows(SEASON, 23)
    assert rows["player_id"].tolist() == [3, 4, 5]
    assert {"team", "team_label", "points_per_game", "true_shooting_pct"} <= set(rows.columns)


# --- The real warehouse ----------------------------------------------------------

REAL = "2024-25"
HOLIDAY = 201950
TATUM = 1628369


def test_the_real_warehouse_has_the_profile(con):
    assert diagnosis.profile_available()
    profile = diagnosis.team_profile(REAL)
    assert len(profile) == 30
    assert profile["defensive_rating_rank"].between(1, 30).all()


def test_bos_2024_25_rotation(con):
    rows = diagnosis.team_drivers(REAL, "BOS")
    assert (rows["games_played"] >= 10).all()
    assert TATUM in set(rows["player_id"])
    assert rows["minutes"].is_monotonic_decreasing
    # The rotation can't take more threes than the whole team did.
    assert 0.8 < rows["team_three_pa_share"].sum() <= 1.0
    holiday = rows.set_index("player_id").loc[HOLIDAY]
    assert holiday["def_on_minus_off"] == pytest.approx(-4.6, abs=0.2)
    for col in D.driver_measures():
        assert rows[f"{col}_league_median"].nunique() == 1, col


def test_real_medians_match_a_direct_query(con):
    expected = con.execute(
        """
        select median(s.true_shooting_pct)
        from main_marts.mart_player_percentiles p
        join main_marts.mart_player_season s using (season, player_id)
        where p.season = ? and p.is_qualified
        """,
        [REAL],
    ).fetchone()[0]
    rows = diagnosis.team_drivers(REAL, "BOS")
    assert rows["true_shooting_pct_league_median"].iloc[0] == pytest.approx(expected)


def test_real_league_rows_and_percentiles(con):
    rows = diagnosis.league_player_rows(REAL, 25)
    assert (rows["games_played"] >= 25).all()
    assert TATUM in set(rows["player_id"])
    tatum = diagnosis.player_percentiles(REAL, TATUM)
    assert tatum is not None and bool(tatum["is_qualified"])
    assert 0 <= tatum["points_per_game_pctile"] <= 100
