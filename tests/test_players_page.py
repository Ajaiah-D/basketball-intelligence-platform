"""The Players page (dashboard/views/players/), rendered with AppTest: the
player search above the tabs, the All players tab's season box, filters and
column sets, the preset player, and the Player tab's game log and trend.

The page's own season box mirrors the sidebar's season picker (key "season"), which every
season-scoped page reads: changing either one changes both. Runs against
the real warehouse via the `con` fixture, like test_db_metrics.py.
"""

import json
import shutil

import duckdb
import pandas as pd
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from core import paths
from dashboard.lib.data import advanced, players, seasons
from dashboard.lib.data import core as data_core
from dashboard.lib.state import PLAYERS_PICK_KEY
from dashboard.lib.stats import qualification_threshold
from dashboard.views.players import table
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


def _open_tab(at: AppTest, label: str) -> AppTest:
    """Switch tabs the way the page itself does (lib.tabs.open_tab)."""
    at.session_state["players_tab__next"] = label
    at.run()
    assert not at.exception, at.exception
    assert at.session_state["players_tab"] == label
    return at


def _texts(at: AppTest) -> str:
    return " ".join(m.value for m in at.markdown)


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
    at.button_group(key="players_scope").set_value("Career").run()
    assert not at.exception, at.exception
    box = at.selectbox(key="players_season_all")
    assert box.disabled and box.value == "All seasons"


# --- The min-games slider follows the season -------------------------------------

LIVE = "2026-27"
FULL = "2025-26"


@pytest.mark.full_warehouse
def test_early_in_a_season_the_table_still_lists_players(con):
    # A week into 2026-27 nobody has 25 games; the default scales down.
    at = _app()
    assert at.selectbox(key="players_season").value == LIVE
    expected = qualification_threshold(players.player_season_stats(LIVE))
    assert expected < 25
    assert at.slider(key="players_min_gp").value == expected
    assert len(at.dataframe[0].value) > 0


@pytest.mark.full_warehouse
def test_a_full_season_defaults_to_25_games_and_a_new_season_resets_it(con):
    at = _app()
    at.selectbox(key="season").select(FULL).run()
    assert not at.exception, at.exception
    assert at.slider(key="players_min_gp").value == 25
    at.slider(key="players_min_gp").set_value(40).run()
    assert at.slider(key="players_min_gp").value == 40
    at.selectbox(key="season").select(LIVE).run()
    assert at.slider(key="players_min_gp").value < 25


def test_the_slider_comes_back_at_the_rule_after_career_scope(con):
    # Career scope drops the keyed slider's state; back in Season scope it
    # returns at the season's rule, not at 1.
    newest = seasons.seasons()[0]
    expected = qualification_threshold(players.player_season_stats(newest))
    at = _app()
    at.button_group(key="players_scope").set_value("Career").run()
    at.button_group(key="players_scope").set_value("Season").run()
    assert not at.exception, at.exception
    assert at.slider(key="players_min_gp").value == expected


def test_the_table_filters_survive_a_visit_to_another_tab(con):
    # Only the active tab renders, so the filters are not drawn while the
    # Player tab is open; coming back finds them as they were.
    at = _app()
    team = at.selectbox(key="players_team").options[1]
    at.selectbox(key="players_team").select(team).run()
    min_gp = at.slider(key="players_min_gp").value + 1  # not the default
    at.slider(key="players_min_gp").set_value(min_gp).run()
    at.button_group(key="players_columns").set_value("Shooting").run()
    at.text_input(key="players_filter").input("a").run()
    _open_tab(at, "Player")
    _open_tab(at, "All players")
    widgets = [
        at.selectbox(key="players_team"),
        at.slider(key="players_min_gp"),
        at.button_group(key="players_columns"),
        at.button_group(key="players_scope"),
        at.text_input(key="players_filter"),
    ]
    assert [w.value for w in widgets] == [team, min_gp, "Shooting", "Season", "a"]
    # The browser forgot them when they were taken off the page, so the
    # values must be sent with the widgets, not just kept on the server.
    assert all(w.proto.set_value for w in widgets)


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
    at.text_input(key="players_filter").input(name).run()
    assert not at.exception, at.exception
    shown = at.dataframe[0].value
    assert "season" in shown.columns
    hit = shown[shown["player"] == name]
    assert list(hit["season"]) == [last]
    assert "didn't play" in " ".join(c.value for c in at.caption)

    # A click on his row opens him at that season: the rows the click is
    # read against carry it.
    rows = at.session_state[table.TABLE_ROWS_KEY]
    picked = rows.iloc[list(shown["player"]).index(name)]
    assert picked["season"] == last
    at.session_state["players_player_id"] = int(picked["player_id"])
    at.session_state["players_player_season"] = picked["season"]
    _open_tab(at, "Player")
    assert name in _texts(at) and last in _texts(at)


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
    at.text_input(key="players_filter").input(name).run()
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


def _short_season_player(con) -> tuple[str, str, int]:
    """The newest season with a player on 10-24 games (in a team's rotation,
    but under a full season's 25-game floor), and that player. The newest
    season itself has nobody on 10+ games in its first weeks."""
    row = con.execute(
        """
        select season, player_name, games_played
        from main_marts.mart_player_season
        where games_played between 10 and 24
        order by season desc, player_name
        limit 1
        """
    ).fetchone()
    assert row, "no 10-24 game player in any season"
    return row[0], row[1], int(row[2])


def _player_id(con, season: str, name: str) -> int:
    row = con.execute(
        "select player_id from main_marts.mart_player_season where season = ? and player_name = ?",
        [season, name],
    ).fetchone()
    assert row, f"{name} not in {season}"
    return int(row[0])


def test_a_preset_player_opens_the_player_tab_even_under_the_games_floor(con):
    season, name, games = _short_season_player(con)
    at = AppTest.from_string(SCRIPT, default_timeout=60)
    at.session_state["season"] = season
    at.session_state[PLAYERS_PICK_KEY] = name
    at.run()
    assert not at.exception, at.exception
    assert at.session_state["players_tab"] == "Player"
    assert at.session_state["players_player_id"] == _player_id(con, season, name)
    assert at.session_state["players_player_season"] == season
    # Read once: the page doesn't keep reopening him.
    assert PLAYERS_PICK_KEY not in at.session_state
    assert name in _texts(at)
    # Another rerun (any widget) keeps him.
    at.run()
    assert name in _texts(at)
    # The min-games slider dropped to his games, so back on All players he
    # is in the table.
    _open_tab(at, "All players")
    assert at.slider(key="players_min_gp").value == games
    assert name in set(at.dataframe[0].value["player"])


def test_a_preset_nobody_has_is_ignored(con):
    at = AppTest.from_string(SCRIPT, default_timeout=60)
    at.session_state[PLAYERS_PICK_KEY] = "Nobody At All"
    at.run()
    assert not at.exception, at.exception
    assert at.session_state["players_tab"] == "All players"
    # The slider stays at the newest season's default.
    newest = seasons.seasons()[0]
    expected = qualification_threshold(players.player_season_stats(newest))
    assert at.slider(key="players_min_gp").value == expected
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


def test_the_page_has_four_tabs(con):
    at = _app()
    assert [t.label for t in at.tabs] == ["All players", "Player", "Compare", "Scatter"]
    assert at.session_state["players_tab"] == "All players"


def _current_player(con) -> tuple[int, str]:
    """(id, name) of the newest season's top scorer with a name nobody else has."""
    newest = seasons.seasons()[0]
    row = con.execute(
        """
        select player_id, player_name from main_marts.mart_player_season
        where season = ? and player_name in (
            select player_name from main_marts.mart_player_season
            group by player_name having count(distinct player_id) = 1
        )
        order by points_per_game desc nulls last, player_id
        limit 1
        """,
        [newest],
    ).fetchone()
    assert row, f"nobody in {newest}"
    return int(row[0]), row[1]


def test_the_search_opens_the_player_tab(con):
    player_id, name = _current_player(con)
    at = _app()
    search = at.selectbox(key="players_search")
    assert search.value is None
    search.select(player_id).run()
    assert not at.exception, at.exception
    assert at.session_state["players_tab"] == "Player"
    assert at.session_state["players_player_id"] == player_id
    assert at.session_state["players_player_season"] == seasons.seasons()[0]
    assert name in _texts(at)
    # It empties itself, so picking the same player again later still works.
    assert at.selectbox(key="players_search").value is None


def test_the_search_opens_a_retired_player_at_his_latest_season(con):
    newest, _ = _two_seasons()
    name, last = _unique_name(
        con,
        "player_id not in (select player_id from main_marts.mart_player_season where season = ?)",
        (newest,),
    )
    player_id = _player_id(con, last, name)
    at = _app()
    at.selectbox(key="players_search").select(player_id).run()
    assert not at.exception, at.exception
    assert at.session_state["players_player_season"] == last
    assert name in _texts(at) and last in _texts(at)


def _index_row(player_id: int) -> pd.Series:
    index = players.all_players_index()
    return index[index["player_id"] == player_id].iloc[0]


def test_the_search_labels_name_team_and_latest_season(con):
    row = con.execute(
        """
        select player_id, player_name from main_marts.mart_player_season
        where player_name = strip_accents(player_name)
        order by season desc, points_per_game desc nulls last limit 1
        """
    ).fetchone()
    player_id, name = int(row[0]), row[1]
    hit = _index_row(player_id)
    at = _app()
    options = at.selectbox(key="players_search").options
    assert f"{name} · {hit['team']} · {hit['latest_season']}" in options


def test_an_accented_name_is_labelled_with_its_plain_spelling_too(con):
    # The select filters on the label as typed, accents and all; the plain
    # spelling beside the name is what lets "jokic" find "Jokić".
    row = con.execute(
        """
        select player_id, player_name from main_marts.mart_player_season
        where player_name <> strip_accents(player_name)
        order by season desc, points_per_game desc nulls last limit 1
        """
    ).fetchone()
    if row is None:
        pytest.skip("no accented names in this warehouse")
    player_id, name = int(row[0]), row[1]
    hit = _index_row(player_id)
    plain = con.execute("select strip_accents(?)", [name]).fetchone()[0]
    at = _app()
    options = at.selectbox(key="players_search").options
    assert f"{name} ({plain}) · {hit['team']} · {hit['latest_season']}" in options


def test_selecting_a_row_opens_that_player(monkeypatch):
    # Row clicks can't be made through AppTest; this is the dataframe's
    # on_select callback, fed the selection Streamlit would hand it.
    rows = pd.DataFrame({"player_id": [11, 22], "season": ["2024-25", "2019-20"], "career": False})
    monkeypatch.setattr(
        st,
        "session_state",
        {"players_table": {"selection": {"rows": [1]}}, table.TABLE_ROWS_KEY: rows},
    )
    opened = []
    monkeypatch.setattr(table, "open_player", lambda *a, **k: opened.append((a, k)))
    table._on_select("players_table", table.TABLE_ROWS_KEY)
    assert opened == [((22, "2019-20"), {"career": False})]

    st.session_state["players_table"] = {"selection": {"rows": [0]}}
    table._on_select("players_table", table.TABLE_ROWS_KEY)
    assert opened[-1] == ((11, "2024-25"), {"career": False})

    # A click on a cell (anywhere in the row, not just its checkbox) opens
    # that row's player too.
    st.session_state["players_table"] = {"selection": {"rows": [], "cells": [(1, "ppg")]}}
    table._on_select("players_table", table.TABLE_ROWS_KEY)
    assert opened[-1] == ((22, "2019-20"), {"career": False})

    # A cleared selection (the row clicked again) opens nobody.
    st.session_state["players_table"] = {"selection": {"rows": [], "cells": []}}
    table._on_select("players_table", table.TABLE_ROWS_KEY)
    assert len(opened) == 3


def test_the_player_tab_opens_on_the_tables_top_row_when_nobody_is_picked(con):
    at = _app()
    top = at.dataframe[0].value.iloc[0]["player"]
    _open_tab(at, "Player")
    assert top in _texts(at)


# --- The All players tab's column sets --------------------------------------------


def test_the_basic_set_is_the_default(con):
    at = _app()
    assert at.button_group(key="players_columns").value == "Basic"
    cols = list(at.dataframe[0].value.columns)
    assert cols[:3] == ["player", "team_label", "gp"]
    assert {"ppg", "rpg", "apg", "spg", "bpg", "plus_minus"} <= set(cols)
    assert "fg_pct" not in cols


def test_the_shooting_set(con):
    at = _app()
    at.button_group(key="players_columns").set_value("Shooting").run()
    assert not at.exception, at.exception
    cols = set(at.dataframe[0].value.columns)
    assert {"fg_pct", "fga_pg", "tpg", "tpa_pg", "fg3_pct", "ft_pct", "fta_pg", "ts_pct"} <= cols
    assert "rpg" not in cols


def test_the_advanced_columns_come_from_the_mart(con):
    at = _app()
    assert "Advanced" in at.button_group(key="players_columns").options
    at.button_group(key="players_columns").set_value("Advanced").run()
    assert not at.exception, at.exception
    shown = at.dataframe[0].value
    assert {"usage_pct", "game_score", "effective_fg_pct", "turnover_pct"} <= set(shown.columns)
    # Joined on the player, so the values are his own season's.
    newest = seasons.seasons()[0]
    mart = con.execute(
        "select player_name, usage_pct from main_marts.mart_player_season "
        "where season = ? and usage_pct is not null order by minutes desc limit 1",
        [newest],
    ).fetchone()
    hit = shown[shown["player"] == mart[0]]
    assert len(hit) == 1 and hit["usage_pct"].iloc[0] == pytest.approx(mart[1])


def test_advanced_columns_are_off_in_career_scope(con):
    at = _app()
    at.button_group(key="players_columns").set_value("Advanced").run()
    at.button_group(key="players_scope").set_value("Career").run()
    assert not at.exception, at.exception
    assert "Advanced" not in at.button_group(key="players_columns").options
    cols = set(at.dataframe[0].value.columns)
    assert "usage_pct" not in cols and {"ppg", "rpg", "apg"} <= cols
    assert "Advanced stats" in " ".join(c.value for c in at.caption)


def test_advanced_columns_are_off_before_the_box_score_is_complete(con):
    old = seasons.seasons()[-1]
    at = AppTest.from_string(SCRIPT, default_timeout=60)
    at.session_state["season"] = old
    at.run()
    assert not at.exception, at.exception
    if old in advanced.advanced_seasons():
        pytest.skip("the warehouse's oldest season has advanced stats")
    assert "Advanced" not in at.button_group(key="players_columns").options


def test_all_players_index_lists_retired_players(con):
    index = players.all_players_index()
    assert list(index.columns) == ["player_id", "player", "team", "latest_season"]
    assert len(index) > 3000
    assert index["player_id"].is_unique
    # Newest seasons first.
    assert list(index["latest_season"]) == sorted(index["latest_season"], reverse=True)
    name, _ = _unique_name(
        con,
        "player_id not in (select player_id from main_marts.mart_player_season "
        "where season >= '2000-01')",
    )
    latest = players.player_latest_seasons(name)
    assert len(latest) == 1
    row = index[index["player_id"] == latest["player_id"].iloc[0]].iloc[0]
    assert row["latest_season"] == latest["season"].iloc[0]
    assert row["player"] == name


# --- The Player tab's game log and trend ---------------------------------------------


def test_the_game_log_lists_every_game(con):
    name, games = _busiest_player(con, "2024-25")
    at = _preset_app("2024-25", name)
    assert _game_log_rows(at) == games
    assert "season average" in " ".join(c.value for c in at.caption)


@pytest.mark.full_warehouse
def test_luka_doncics_2025_26_game_log(con):
    at = _preset_app("2025-26", "Luka Dončić")
    assert at.session_state["players_player_id"] == _player_id(con, "2025-26", "Luka Dončić")
    assert _game_log_rows(at) == 64


def test_the_trend_picker_switches_the_chart(con):
    name, _ = _busiest_player(con, "2024-25")
    at = _preset_app("2024-25", name)
    assert "Points" in _trend_title(at)
    at.button_group(key=TREND_KEY).set_value("AST").run()
    assert not at.exception, at.exception
    assert "Assists" in _trend_title(at)
    at.button_group(key=TREND_KEY).set_value("TS%").run()
    assert "True shooting" in _trend_title(at)


def test_a_preset_player_gets_his_own_game_log(con):
    season, name, games = _short_season_player(con)
    at = _preset_app(season, name)
    assert at.session_state["players_player_id"] == _player_id(con, season, name)
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
    # The rest of the detail still draws: the shooting section below it.
    assert "#### Shooting" in _texts(at)
    assert "#### Game log" not in _texts(at)


# --- The Player tab's sections -------------------------------------------------------


def _player_app(con) -> AppTest:
    """The Player tab on the newest season's top scorer, opened by the search."""
    player_id, _name = _current_player(con)
    at = _app()
    at.selectbox(key="players_search").select(player_id).run()
    assert not at.exception, at.exception
    return at


def _axis_titles(at: AppTest) -> list[str]:
    return [
        json.loads(c.proto.spec)["layout"].get("xaxis", {}).get("title", {}).get("text", "")
        for c in at.get("plotly_chart")
    ]


def test_the_player_tab_has_its_sections(con):
    text = _texts(_player_app(con))
    titles = ["#### Game by game", "#### Shooting", "#### Advanced", "#### Game log"]
    assert all(t in text for t in titles), [t for t in titles if t not in text]
    assert [text.index(t) for t in titles] == sorted(text.index(t) for t in titles)


def test_the_advanced_section_ranks_him_among_players_over_the_minutes_floor(con):
    name, _ = _busiest_player(con, "2024-25")
    at = _preset_app("2024-25", name)
    captions = " ".join(c.value for c in at.caption)
    assert "Percentile among players with" in captions
    assert "TOV%" not in captions  # not one of the ranked metrics
    assert any("minutes" in t for t in _axis_titles(at))


def test_advanced_section_hides_without_the_mart(con, monkeypatch):
    monkeypatch.setattr(advanced, "marts_available", lambda: False)
    name, _ = _busiest_player(con, "2024-25")
    at = _preset_app("2024-25", name)
    assert "#### Advanced" in _texts(at)
    assert "No advanced stats" in " ".join(c.value for c in at.caption)
    assert not any("minutes" in t for t in _axis_titles(at))


def test_a_player_under_the_minutes_floor_is_not_ranked(con):
    row = con.execute(
        """
        select player_name from main_marts.mart_player_season
        where season = '2024-25' and minutes between 1 and 40
          and player_name in (
              select player_name from main_marts.mart_player_season
              where season = '2024-25' group by player_name having count(*) = 1
          )
        order by player_name limit 1
        """
    ).fetchone()
    if row is None:
        pytest.skip("nobody under 40 minutes in 2024-25")
    at = _preset_app("2024-25", row[0])
    assert "too few to rank" in " ".join(c.value for c in at.caption)
    assert not any("minutes" in t for t in _axis_titles(at))


def test_the_player_scope_survives_a_visit_to_another_tab(con):
    at = _player_app(con)
    at.button_group(key="players_player_scope").set_value("Career").run()
    assert not at.exception, at.exception
    _open_tab(at, "Compare")
    _open_tab(at, "Player")
    toggle = at.button_group(key="players_player_scope")
    assert toggle.value == "Career"
    assert toggle.proto.set_value  # sent to the browser, not just kept on the server
    assert "#### Career trajectory" in _texts(at)


def test_the_default_player_follows_a_career_table(con):
    at = _app()
    at.button_group(key="players_scope").set_value("Career").run()
    top = at.dataframe[0].value.iloc[0]["player"]
    _open_tab(at, "Player")
    assert at.button_group(key="players_player_scope").value == "Career"
    assert top in _texts(at) and "#### Career trajectory" in _texts(at)
    # Turning the toggle keeps him, now as a chosen player, at that scope.
    at.button_group(key="players_player_scope").set_value("Season").run()
    assert not at.exception, at.exception
    assert at.button_group(key="players_player_scope").value == "Season"
    assert top in _texts(at) and "#### Game by game" in _texts(at)
    assert at.session_state["players_player_id"] is not None
    # Back on a Season table, nothing about the chosen player changes.
    _open_tab(at, "All players")
    at.button_group(key="players_scope").set_value("Season").run()
    _open_tab(at, "Player")
    assert at.button_group(key="players_player_scope").value == "Season"
    assert top in _texts(at)


def test_the_default_player_follows_a_season_table(con):
    at = _app()
    _open_tab(at, "Player")
    assert at.button_group(key="players_player_scope").value == "Season"


def test_the_career_trajectory_picker_switches_the_chart(con):
    at = _player_app(con)
    at.button_group(key="players_player_scope").set_value("Career").run()
    picker = at.button_group(key="players_career_stat")
    assert picker.value == "PPG"
    picker.set_value("TS%").run()
    assert not at.exception, at.exception
    assert "True shooting" in " ".join(c.value for c in at.caption)
