"""The Players page (dashboard/views/players/), rendered with AppTest: its
season box, search, preset player, tabs and the season detail's game log
and trend.

The page's own season box mirrors the sidebar's season picker (key "season"), which every
season-scoped page reads: changing either one changes both. Runs against
the real warehouse via the `con` fixture, like test_db_metrics.py.
"""

import json
import shutil

import duckdb
import pytest
from streamlit.testing.v1 import AppTest

from core import paths
from dashboard.lib.data import core as data_core
from dashboard.lib.data import players, seasons
from dashboard.lib.state import PLAYERS_PICK_KEY
from dashboard.views.players.game_log import TREND_KEY

# The sidebar box from dashboard/app.py, then the page.
SCRIPT = """
import streamlit as st
from dashboard.lib.data import seasons
from dashboard.views import players
with st.sidebar:
    st.selectbox("Season", seasons.seasons(), key="season")
players.render()
"""


def _two_seasons() -> tuple[str, str]:
    every = seasons.seasons()
    if len(every) < 2:
        pytest.skip("needs a warehouse with two seasons")
    return every[0], every[1]


def _app() -> AppTest:
    at = AppTest.from_string(SCRIPT, default_timeout=60)
    at.run()
    assert not at.exception, at.exception
    return at


def test_the_page_season_box_changes_the_shared_season(con):
    newest, older = _two_seasons()
    at = _app()
    assert at.selectbox(key="players_season").value == newest
    at.selectbox(key="players_season").select(older).run()
    assert not at.exception, at.exception
    assert at.session_state["season"] == older
    assert at.selectbox(key="season").value == older
    assert older in " ".join(m.value for m in at.markdown)  # the title chip


def test_the_sidebar_season_moves_the_page_box(con):
    _, older = _two_seasons()
    at = _app()
    at.selectbox(key="season").select(older).run()
    assert not at.exception, at.exception
    assert at.selectbox(key="players_season").value == older


def test_career_scope_shows_all_seasons_and_no_season_choice(con):
    at = _app()
    at.button_group[0].set_value("Career").run()
    assert not at.exception, at.exception
    box = at.selectbox(key="players_season_all")
    assert box.disabled and box.value == "All seasons"


# --- Search finds players outside the selected season -------------------------


def _unique_name(con, where: str, params=()):
    """(name, latest season) of a player whose name no other player shares
    and who never changed its spelling, from mart_player_season rows matching
    `where` with 25+ games (the page's default minimum)."""
    row = con.execute(
        f"""
        with names as (
            select player_id, min(player_name) as player_name
            from main_marts.mart_player_season
            group by player_id
            having count(distinct player_name) = 1
        ),
        unique_names as (
            select player_name from names group by player_name having count(*) = 1
        )
        select n.player_name, max(m.season)
        from main_marts.mart_player_season m
        join names n using (player_id)
        join unique_names u on u.player_name = n.player_name
        where m.games_played >= 25 and {where}
        group by n.player_name
        order by max(m.season) desc
        limit 1
    """,
        list(params),
    ).fetchone()
    if row is None:
        pytest.skip("no suitable player in this warehouse")
    return row


def test_search_finds_a_retired_player_at_his_latest_season(con):
    newest, _ = _two_seasons()
    name, last = _unique_name(
        con,
        "player_id not in (select player_id from main_marts.mart_player_season where season = ?)",
        (newest,),
    )
    at = _app()
    at.text_input[0].input(name).run()
    assert not at.exception, at.exception
    table = at.dataframe[0].value
    assert "season" in table.columns
    hit = table[table["player"] == name]
    assert list(hit["season"]) == [last]
    assert "didn't play" in " ".join(c.value for c in at.caption)

    # The detail section follows that season.
    at.selectbox(key="players_pick").select(f"{name} ({last})").run()
    assert not at.exception, at.exception
    assert last in " ".join(m.value for m in at.markdown)


def _established_season(con) -> str:
    """The newest season in which someone has played 25+ games (the page's
    default minimum): early in a season the newest one has nobody yet."""
    row = con.execute(
        "select max(season) from main_marts.mart_player_season where games_played >= 25"
    ).fetchone()
    if row is None or row[0] is None:
        pytest.skip("no season with a 25-game player in this warehouse")
    return str(row[0])


def test_search_keeps_the_selected_season_for_players_in_it(con):
    season = _established_season(con)
    name, _last = _unique_name(con, "season = ?", (season,))
    at = _app()
    at.selectbox(key="players_season").select(season).run()
    assert not at.exception, at.exception
    at.text_input[0].input(name).run()
    assert not at.exception, at.exception
    table = at.dataframe[0].value
    assert list(table["player"]) == [name]
    assert "season" not in table.columns  # nothing from another season to mark


def test_latest_seasons_search_ignores_case_and_accents(con):
    row = con.execute("""
        select player_id, player_name from main_marts.mart_player_season
        where player_name <> strip_accents(player_name) and games_played >= 25
        limit 1""").fetchone()
    if row is None:
        pytest.skip("no accented names in this warehouse")
    player_id, name = row
    plain = con.execute("select upper(strip_accents(?))", [name]).fetchone()[0]
    found = players.player_latest_seasons(plain, 25)  # "VALANCIUNAS" for "Valančiūnas"
    assert player_id in set(found["player_id"])


# --- A player preset by another page (Teams' "Open on Players") ------------------


def _short_season_player(con, season: str) -> tuple[str, int]:
    """A player with 10-24 games that season: in a team's rotation, but
    under the page's default 25-game floor."""
    row = con.execute(
        """
        select player_name, games_played
        from main_marts.mart_player_season
        where season = ? and games_played between 10 and 24
        order by player_name
        limit 1
        """,
        [season],
    ).fetchone()
    assert row, f"no 10-24 game player in {season}"
    return row[0], int(row[1])


def test_a_preset_player_opens_even_under_the_games_floor(con):
    season = seasons.latest_season()
    name, games = _short_season_player(con, season)
    at = AppTest.from_string(SCRIPT, default_timeout=60)
    at.session_state["season"] = season
    at.session_state[PLAYERS_PICK_KEY] = name
    at.run()
    assert not at.exception, at.exception
    assert at.selectbox(key="players_pick").value == name
    assert at.slider(key="players_min_gp").value == games
    # Read once: the page doesn't keep reopening him.
    assert PLAYERS_PICK_KEY not in at.session_state
    assert name in " ".join(m.value for m in at.markdown)
    # Another rerun (any widget) keeps him, since the slider stays lowered.
    at.run()
    assert at.selectbox(key="players_pick").value == name


def test_a_preset_nobody_has_is_ignored(con):
    at = AppTest.from_string(SCRIPT, default_timeout=60)
    at.session_state[PLAYERS_PICK_KEY] = "Nobody At All"
    at.run()
    assert not at.exception, at.exception
    assert at.slider(key="players_min_gp").value == 25
    assert PLAYERS_PICK_KEY not in at.session_state


# --- The tabs, and the season detail's game log and trend ---------------------------


def _preset_app(season: str, name: str) -> AppTest:
    at = AppTest.from_string(SCRIPT, default_timeout=60)
    at.session_state["season"] = season
    at.session_state[PLAYERS_PICK_KEY] = name
    at.run()
    assert not at.exception, at.exception
    return at


def _game_log_rows(at: AppTest) -> int:
    """Rows in the game log: the one table that scrolls inside a fixed height."""
    logs = [m.value for m in at.markdown if "bip-scroll" in m.value]
    assert len(logs) == 1
    return logs[0].count("<tr") - 1  # less the header


def _trend_title(at: AppTest) -> str:
    titles = [
        json.loads(c.proto.spec)["layout"].get("title", {}).get("text", "")
        for c in at.get("plotly_chart")
    ]
    found = [t for t in titles if t.endswith("by game")]
    assert len(found) == 1
    return found[0]


def _busiest_player(con, season: str) -> tuple[str, int]:
    """(name, games) of a 25+ game player that season, most games first."""
    row = con.execute(
        """
        select player_name, games_played from main_marts.mart_player_season
        where season = ? and games_played >= 25
        order by games_played desc, points_per_game desc, player_name
        limit 1
        """,
        [season],
    ).fetchone()
    assert row, f"no 25-game player in {season}"
    return row[0], int(row[1])


def test_the_page_has_stats_scatter_and_compare_tabs(con):
    at = _app()
    assert [t.label for t in at.tabs] == ["Stats", "Scatter", "Compare"]
    # The tabs to come say what they will hold, in one line each.
    assert len(at.tabs[1].caption) == 1 and len(at.tabs[2].caption) == 1


def test_the_game_log_lists_every_game(con):
    name, games = _busiest_player(con, "2024-25")
    at = _preset_app("2024-25", name)
    assert _game_log_rows(at) == games
    assert "season average" in " ".join(c.value for c in at.caption)


@pytest.mark.full_warehouse
def test_luka_doncics_2025_26_game_log(con):
    at = _preset_app("2025-26", "Luka Dončić")
    assert at.selectbox(key="players_pick").value == "Luka Dončić"
    assert _game_log_rows(at) == 64


def test_the_trend_picker_switches_the_chart(con):
    name, _ = _busiest_player(con, "2024-25")
    at = _preset_app("2024-25", name)
    assert "Points" in _trend_title(at)
    at.selectbox(key=TREND_KEY).select("AST").run()
    assert not at.exception, at.exception
    assert "Assists" in _trend_title(at)
    at.selectbox(key=TREND_KEY).select("TS%").run()
    assert "True shooting" in _trend_title(at)


def test_a_preset_player_gets_his_own_game_log(con):
    season = seasons.latest_season()
    name, games = _short_season_player(con, season)
    at = _preset_app(season, name)
    assert at.selectbox(key="players_pick").value == name
    assert _game_log_rows(at) == games


@pytest.fixture
def warehouse_without_game_mart(con, tmp_path):
    """A copy of the real warehouse as published before mart_player_game. It
    keeps the file name: dbt's views name the catalog, which DuckDB takes
    from the file name."""
    real = paths.warehouse_path()
    path = tmp_path / real.name
    shutil.copyfile(real, path)
    copy = duckdb.connect(str(path))
    copy.execute("drop view main_marts.mart_player_game")
    copy.close()
    with data_core.use_warehouse(path):
        yield path


def test_without_the_game_mart_the_detail_shows_one_notice(warehouse_without_game_mart):
    con = duckdb.connect(str(warehouse_without_game_mart), read_only=True)
    name, _ = _busiest_player(con, "2024-25")
    con.close()
    at = _preset_app("2024-25", name)
    assert len(at.info) == 1
    assert "next data refresh" in at.info[0].value
    assert not [m for m in at.markdown if "bip-scroll" in m.value]
    # The rest of the detail still draws: the shooting chart beside it.
    assert "Shooting vs league" in " ".join(m.value for m in at.markdown)
