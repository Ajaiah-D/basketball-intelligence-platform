"""dashboard/lib/data/schedule.py: the season's games with results, the
latest prediction and the top scorer; the calendar's day counts; one
team's season with its running record.

A synthetic warehouse covers the shapes (a tie for top scorer, a
neutral-site game whose result is oriented the other way, a cancelled 0-0
game, a re-predicted game, a preseason game) and the real one the facts."""

from datetime import date

import duckdb
import pandas as pd
import pytest

from dashboard.lib.data import core as data_core
from dashboard.lib.data import schedule

SEASON = "2030-31"

COLUMNS = [
    "game_id",
    "game_date",
    "tipoff_utc",
    "home",
    "away",
    "home_id",
    "away_id",
    "home_points",
    "away_points",
    "is_final",
    "win_probability",
    "predicted_margin",
    "top_scorer",
    "top_points",
]

IDS = {"BOS": 1, "NYK": 2, "MIA": 3, "DAL": 4}

# (game_id, date, tipoff_utc, home, away)
GAMES = [
    ("0013000001", "2030-10-10", "2030-10-10 23:00:00", "BOS", "NYK"),  # preseason
    ("0023000001", "2030-10-20", "2030-10-20 23:30:00", "BOS", "NYK"),
    ("0023000002", "2030-10-22", "2030-10-23 00:00:00", "NYK", "BOS"),
    ("0023000003", "2030-10-22", "2030-10-22 19:00:00", "MIA", "DAL"),  # neutral
    ("0023000004", "2030-10-25", "2030-10-25 23:00:00", "BOS", "MIA"),  # upcoming
    ("0023000005", "2030-11-02", "2030-11-02 23:00:00", "BOS", "DAL"),  # cancelled
]

# fct_team_game rows: (game_id, home, away, home_points, away_points).
# The neutral game is oriented DAL-home there, the other way round.
RESULTS = [
    ("0023000001", "BOS", "NYK", 112, 105),
    ("0023000002", "NYK", "BOS", 100, 99),
    ("0023000003", "DAL", "MIA", 90, 95),
    ("0023000005", "BOS", "DAL", 0, 0),
]

# (game_id, player, points)
LOGS = [
    ("0023000001", "Zed Zulu", 30),
    ("0023000001", "Abe Able", 30),
    ("0023000001", "Cal Cole", 12),
    ("0023000002", "Cal Cole", 41),
    ("0023000003", "Dan Dee", None),
    ("0023000003", "Eli Eck", 22),
]

# (prediction_id, predicted_at, game_id, win_probability, predicted_margin)
PREDICTIONS = [
    ("p1", "2030-10-19 10:00:00", "0023000001", 0.61, 3.0),
    ("p2", "2030-10-23 10:00:00", "0023000004", 0.55, 1.5),
    ("p3", "2030-10-24 10:00:00", "0023000004", 0.65, 5.0),
]


def _table(con, name, df):
    con.register("df_view", df)
    con.execute(f"create table {name} as select * from df_view")
    con.unregister("df_view")


def _build(path, with_predictions=True):
    con = duckdb.connect(str(path))
    con.execute("create schema main_staging")
    con.execute("create schema main_marts")
    _table(
        con,
        "main_staging.stg_schedule",
        pd.DataFrame(
            [
                {
                    "season": SEASON,
                    "game_id": gid,
                    "game_date": pd.Timestamp(day).date(),
                    "tipoff_utc": pd.Timestamp(tip),
                    "home_team_id": IDS[home],
                    "home_team_abbreviation": home,
                    "away_team_id": IDS[away],
                    "away_team_abbreviation": away,
                    "game_status": 1 if gid == "0023000004" else 3,
                    "is_regular_season": gid.startswith("002"),
                }
                for gid, day, tip, home, away in GAMES
            ]
        ),
    )
    _table(
        con,
        "main_marts.fct_team_game",
        pd.DataFrame(
            [
                {
                    "season": SEASON,
                    "game_id": gid,
                    "home_team_id": IDS[home],
                    "home_team_abbreviation": home,
                    "away_team_id": IDS[away],
                    "away_team_abbreviation": away,
                    "home_points": hp,
                    "away_points": ap,
                }
                for gid, home, away, hp, ap in RESULTS
            ]
        ),
    )
    logs = pd.DataFrame(LOGS, columns=["game_id", "player_name", "points"])
    logs["season"] = SEASON
    logs["points"] = logs["points"].astype("Int64")
    _table(con, "main_staging.stg_player_game_logs", logs)
    if with_predictions:
        preds = pd.DataFrame(
            PREDICTIONS,
            columns=[
                "prediction_id",
                "predicted_at",
                "game_id",
                "win_probability",
                "predicted_margin",
            ],
        )
        preds["predicted_at"] = pd.to_datetime(preds["predicted_at"])
        _table(con, "main.predictions", preds)
    con.close()
    return path


@pytest.fixture
def schedule_warehouse(tmp_path):
    path = _build(tmp_path / "schedule.duckdb")
    with data_core.use_warehouse(path):
        yield path


@pytest.fixture
def schedule_warehouse_without_predictions(tmp_path):
    path = _build(tmp_path / "schedule_no_predictions.duckdb", with_predictions=False)
    with data_core.use_warehouse(path):
        yield path


def _game(df, game_id):
    return df.set_index("game_id").loc[game_id]


# --- Synthetic warehouse ---------------------------------------------------------


def test_one_row_per_regular_season_game(schedule_warehouse):
    games = schedule.schedule(SEASON)
    assert list(games.columns) == COLUMNS
    assert games["game_id"].tolist() == [
        "0023000001",
        "0023000003",
        "0023000002",
        "0023000004",
        "0023000005",
    ]


def test_a_finished_game_has_its_score_and_top_scorer(schedule_warehouse):
    game = _game(schedule.schedule(SEASON), "0023000001")
    assert bool(game["is_final"])
    assert (game["home"], game["away"]) == ("BOS", "NYK")
    assert (game["home_points"], game["away_points"]) == (112, 105)
    # Zulu and Able both scored 30; the name breaks the tie.
    assert (game["top_scorer"], game["top_points"]) == ("Abe Able", 30)
    assert game["win_probability"] == pytest.approx(0.61)


def test_a_neutral_game_is_scored_from_the_schedules_home_side(schedule_warehouse):
    game = _game(schedule.schedule(SEASON), "0023000003")
    assert (game["home"], game["home_points"], game["away_points"]) == ("MIA", 95, 90)
    assert game["top_scorer"] == "Eli Eck"


def test_an_upcoming_game_has_its_latest_prediction(schedule_warehouse):
    game = _game(schedule.schedule(SEASON), "0023000004")
    assert not bool(game["is_final"])
    assert game["win_probability"] == pytest.approx(0.65)
    assert game["predicted_margin"] == pytest.approx(5.0)
    assert pd.isna(game["home_points"]) and pd.isna(game["top_scorer"])
    assert game["tipoff_utc"] == pd.Timestamp("2030-10-25 23:00:00")


def test_a_cancelled_0_0_game_is_not_a_final(schedule_warehouse):
    game = _game(schedule.schedule(SEASON), "0023000005")
    assert not bool(game["is_final"])
    assert pd.isna(game["home_points"])


def test_no_predictions_table_means_no_probabilities(schedule_warehouse_without_predictions):
    games = schedule.schedule(SEASON)
    assert len(games) == 5
    assert games["win_probability"].isna().all()
    assert games["predicted_margin"].isna().all()


def test_an_unscheduled_season_is_empty_with_the_columns(schedule_warehouse):
    games = schedule.schedule("1999-00")
    assert games.empty
    assert list(games.columns) == COLUMNS


def test_month_counts(schedule_warehouse):
    assert schedule.month_counts(SEASON, 2030, 10) == {
        date(2030, 10, 20): 1,
        date(2030, 10, 22): 2,
        date(2030, 10, 25): 1,
    }
    assert schedule.month_counts(SEASON, 2030, 11) == {date(2030, 11, 2): 1}
    assert schedule.month_counts(SEASON, 2030, 12) == {}


def test_team_schedule_has_results_and_a_running_record(schedule_warehouse):
    bos = schedule.team_schedule(SEASON, "BOS")
    assert bos["game_id"].tolist() == ["0023000001", "0023000002", "0023000004", "0023000005"]
    assert bos["opponent"].tolist() == ["NYK", "NYK", "MIA", "DAL"]
    assert bos["is_home"].tolist() == [True, False, True, True]
    assert bos["result"].tolist() == ["W 112-105", "L 99-100", "", ""]
    assert bos["record"].tolist() == ["1-0", "1-1", "", ""]


def test_team_schedule_for_a_team_without_games(schedule_warehouse):
    none = schedule.team_schedule(SEASON, "ZZZ")
    assert none.empty
    assert {"opponent", "is_home", "result", "record"} <= set(none.columns)


# --- The real warehouse ----------------------------------------------------------

UPCOMING_SEASON = "2026-27"
BOS_NYK = "0022600008"  # 2026-10-23, NYK at BOS


def test_the_real_2026_27_schedule(con):
    games = schedule.schedule(UPCOMING_SEASON)
    regular = con.execute(
        "select count(*) from main_staging.stg_schedule where season = ? and is_regular_season",
        [UPCOMING_SEASON],
    ).fetchone()[0]
    assert len(games) == regular == 1206
    assert games["game_id"].is_unique
    game = _game(games, BOS_NYK)
    assert (game["home"], game["away"]) == ("BOS", "NYK")
    assert game["game_date"] == pd.Timestamp("2026-10-23")
    latest = con.execute(
        """
        select win_probability from main.predictions where game_id = ?
        order by predicted_at desc, prediction_id limit 1
        """,
        [BOS_NYK],
    ).fetchone()[0]
    assert game["win_probability"] == pytest.approx(latest)
    # Finished games have both scores, unfinished ones neither.
    finals = games[games["is_final"]]
    assert finals[["home_points", "away_points"]].notna().all().all()
    assert games.loc[~games["is_final"], "home_points"].isna().all()


def test_real_month_counts_add_up(con):
    october = schedule.month_counts(UPCOMING_SEASON, 2026, 10)
    assert october[date(2026, 10, 23)] == 12
    games = schedule.schedule(UPCOMING_SEASON)
    in_october = games["game_date"].dt.month == 10
    assert sum(october.values()) == int(in_october.sum())
    assert schedule.month_counts(UPCOMING_SEASON, 2026, 8) == {}


def test_real_team_schedule_is_every_bos_game(con):
    bos = schedule.team_schedule(UPCOMING_SEASON, "BOS")
    # 80 until the NBA Cup knockout games are scheduled, then up to 82.
    assert 80 <= len(bos) <= 82
    games = schedule.schedule(UPCOMING_SEASON)
    assert len(bos) == int(((games["home"] == "BOS") | (games["away"] == "BOS")).sum())
    assert (bos["opponent"] != "BOS").all()
    row = bos.set_index("game_id").loc[BOS_NYK]
    assert row["opponent"] == "NYK" and bool(row["is_home"])


@pytest.mark.full_warehouse
def test_a_finished_2025_26_game(con):
    """The 2025-26 opener, OKC 125-124 HOU; the fixtures have no 2025-26
    schedule."""
    games = schedule.schedule("2025-26")
    assert len(games) == 1230 and games["is_final"].all()
    opener = _game(games, "0022500001")
    assert (opener["home"], opener["home_points"], opener["away_points"]) == ("OKC", 125, 124)
    assert (opener["top_scorer"], opener["top_points"]) == ("Alperen Sengun", 39)
    okc = schedule.team_schedule("2025-26", "OKC")
    assert (okc.iloc[0]["result"], okc.iloc[0]["record"]) == ("W 125-124", "1-0")
    wins, losses = map(int, okc.iloc[-1]["record"].split("-"))
    assert wins + losses == 82
