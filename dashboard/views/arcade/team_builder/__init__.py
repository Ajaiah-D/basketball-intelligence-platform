"""Build a team: pick eight player-seasons under a budget (Build) or pick
one of three offered players for each spot (Draft), then simulate seasons.

  state.py      the session-state keys and the reset helpers
  build.py      Build mode
  draft.py      Draft mode
  roster.py     the roster grid both modes show
  results.py    the projection both modes end in
  explainer.py  the "How the simulation works" text

This module is the tab: the mode and pool controls, then the right mode.
"""

import streamlit as st

from dashboard.lib.data import arcade as arcade_data
from dashboard.views.arcade.team_builder import state as tb_state
from dashboard.views.arcade.team_builder.build import render_build
from dashboard.views.arcade.team_builder.draft import render_draft
from dashboard.views.arcade.team_builder.explainer import explainer
from dashboard.views.arcade.team_builder.results import model_meta


def render_build_team() -> None:
    if not arcade_data.player_impact_available():
        st.info("Team building needs a newer copy of the data - check back after the next refresh.")
        return
    all_pool = arcade_data.player_impact_pool(None)
    choices = [
        tb_state.ALL_TIME,
        *sorted((str(s) for s in all_pool["season"].unique()), reverse=True),
    ]
    if st.session_state.get(tb_state.MODE) not in tb_state.MODES:
        st.session_state[tb_state.MODE] = tb_state.MODES[0]
    if st.session_state.get(tb_state.POOL) not in choices:
        st.session_state[tb_state.POOL] = tb_state.ALL_TIME

    c1, c2, c3, _ = st.columns([1.1, 1.3, 0.8, 2.8], vertical_alignment="bottom")
    c1.segmented_control(
        "Mode", tb_state.MODES, key=tb_state.MODE, required=True, on_change=tb_state.reset
    )
    c2.selectbox("Player pool", choices, key=tb_state.POOL, on_change=tb_state.reset)
    c3.button("Start over", key="tb_restart", width="stretch", on_click=tb_state.reset)

    choice = st.session_state[tb_state.POOL]
    season = None if choice == tb_state.ALL_TIME else choice
    pool = all_pool if season is None else arcade_data.player_impact_pool(season)
    meta = model_meta()
    if st.session_state[tb_state.MODE] == "Build":
        render_build(pool, season, choice, meta)
    else:
        render_draft(pool, season, choice, meta)
    explainer(arcade_data.player_impact_meta())
