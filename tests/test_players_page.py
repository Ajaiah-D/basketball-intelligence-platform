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
