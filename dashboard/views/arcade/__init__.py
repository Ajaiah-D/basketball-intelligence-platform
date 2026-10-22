"""Arcade - games built on 47 seasons of real NBA data.

  higher_lower.py   Higher or Lower: guess who averaged more
  mystery.py        Mystery Player: identify a season from clues
  team_builder/     Build a team: Build and Draft modes, then simulated seasons
  cards.py          the player-season card the first two games share

Each game keeps its session state under its own prefix (hl*, my*, tb_*);
the keys are documented in its module. This module is the page: a title and
one tab per game.
"""

import streamlit as st

from dashboard.lib.data import seasons
from dashboard.views.arcade.higher_lower import render_higher_lower
from dashboard.views.arcade.mystery import render_mystery
from dashboard.views.arcade.team_builder import render_build_team


def render() -> None:
    n = len(seasons.seasons())
    st.markdown(
        f'## Arcade &nbsp;<span class="bip-chip">{n} seasons of data</span>',
        unsafe_allow_html=True,
    )
    tab_hl, tab_my, tab_tb = st.tabs(["Higher or Lower", "Mystery Player", "Build a team"])
    with tab_hl:
        render_higher_lower()
    with tab_my:
        render_mystery()
    with tab_tb:
        render_build_team()
