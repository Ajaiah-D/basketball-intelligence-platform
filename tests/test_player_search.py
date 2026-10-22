"""players.player_latest_seasons() folds names the way core.text.fold does,
on a tiny synthetic warehouse: a name with a letter DuckDB's strip_accents()
keeps ("ł", "ø", "đ") is found by its plain-ASCII spelling, which the old
SQL-side fold missed."""

import duckdb
import pytest

from dashboard.lib.data import core as data_core
from dashboard.lib.data import players

# (player_id, season, player_name, games_played)
ROWS = [
    (1, "2023-24", "Łukasz Kowalski", 70),
    (1, "2024-25", "Łukasz Kowalski", 20),
    (2, "2024-25", "Bjørn Ødegaard", 50),
    (3, "2024-25", "Đorđe Petrović", 10),
    (4, "2024-25", "Nikola Jokić", 79),
    (5, "2024-25", "Plain Name", 82),
]

COLUMNS = """
    player_id bigint, season varchar, player_name varchar, team varchar,
    games_played integer, minutes_per_game double, points_per_game double,
    rebounds_per_game double, assists_per_game double, steals_per_game double,
    blocks_per_game double, threes_made_per_game double, fga_per_game double,
    three_pa_per_game double, fta_per_game double, fga_total integer,
    tpa_total integer, fta_total integer, fg_pct double, fg3_pct double,
    ft_pct double, true_shooting_pct double, assist_to_turnover double,
    plus_minus_per_game double, team_label varchar
"""


@pytest.fixture
def names_warehouse(tmp_path):
    path = tmp_path / "names.duckdb"
    con = duckdb.connect(str(path))
    con.execute("create schema main_marts")
    con.execute(f"create table main_marts.mart_player_season ({COLUMNS})")
    for player_id, season, name, gp in ROWS:
        con.execute(
            "insert into main_marts.mart_player_season "
            "(player_id, season, player_name, team, games_played, team_label) "
            "values (?, ?, ?, 'AAA', ?, 'AAA')",
            [player_id, season, name, gp],
        )
    con.close()
    with data_core.use_warehouse(path):
        yield path


@pytest.mark.parametrize(
    ("needle", "player_id"),
    [
        ("lukasz", 1),
        ("LUKASZ KOW", 1),
        ("bjorn", 2),
        ("odegaard", 2),
        ("dorde", 3),
        ("petrovic", 3),
        ("jokic", 4),
        ("Jokić", 4),
        ("Łukasz", 1),
    ],
)
def test_a_name_is_found_by_its_plain_spelling(names_warehouse, needle, player_id):
    found = players.player_latest_seasons(needle)
    assert found["player_id"].tolist() == [player_id]


def test_strip_accents_alone_would_miss_them(names_warehouse):
    """Why the fold is not done in SQL: DuckDB leaves these letters alone."""
    with duckdb.connect(str(names_warehouse), read_only=True) as con:
        kept = con.execute("select strip_accents(lower('Łukasz Bjørn Đorđe'))").fetchone()[0]
    assert "lukasz" not in kept and "bjorn" not in kept and "dorde" not in kept


def test_latest_season_and_min_games_still_apply(names_warehouse):
    assert players.player_latest_seasons("lukasz")["season"].tolist() == ["2024-25"]
    older = players.player_latest_seasons("lukasz", min_games=25)
    assert older["season"].tolist() == ["2023-24"]
    assert players.player_latest_seasons("dorde", min_games=25).empty


def test_no_match_and_an_empty_search_return_the_columns_and_no_rows(names_warehouse):
    for needle in ("zzz", "   ", ""):
        found = players.player_latest_seasons(needle)
        assert found.empty
        assert {"player_id", "season", "player", "team_label"} <= set(found.columns)


def test_percent_and_underscore_are_literal(names_warehouse):
    assert players.player_latest_seasons("%").empty
    assert players.player_latest_seasons("_").empty
