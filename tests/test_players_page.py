"""The Players page's own season box (dashboard/views/players.py).

It mirrors the sidebar's season picker (key "season"), which every
season-scoped page reads: changing either one changes both. Runs against
the real warehouse via the `con` fixture, like test_db_metrics.py.
"""

import pytest
from streamlit.testing.v1 import AppTest

from dashboard.lib import db

# The sidebar box from dashboard/app.py, then the page.
SCRIPT = """
import streamlit as st
from dashboard.lib import db
from dashboard.views import players
with st.sidebar:
    st.selectbox("Season", db.seasons(), key="season")
players.render()
"""


def _two_seasons() -> tuple[str, str]:
    seasons = db.seasons()
    if len(seasons) < 2:
        pytest.skip("needs a warehouse with two seasons")
    return seasons[0], seasons[1]


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
    newest, older = _two_seasons()
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
    row = con.execute(f"""
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
    """, list(params)).fetchone()
    if row is None:
        pytest.skip("no suitable player in this warehouse")
    return row


def test_search_finds_a_retired_player_at_his_latest_season(con):
    newest, _ = _two_seasons()
    name, last = _unique_name(con, "player_id not in (select player_id from "
                                   "main_marts.mart_player_season where season = ?)",
                              (newest,))
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


def test_search_keeps_the_selected_season_for_players_in_it(con):
    newest, _ = _two_seasons()
    name, _last = _unique_name(con, "season = ?", (newest,))
    at = _app()
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
    found = db.player_latest_seasons(plain, 25)  # "VALANCIUNAS" for "Valančiūnas"
    assert player_id in set(found["player_id"])
