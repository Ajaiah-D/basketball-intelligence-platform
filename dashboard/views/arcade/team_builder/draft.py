"""Draft mode: eight rounds of "pick one of three" under a hidden budget,
then the shared projection. The CPU-side rules (budget, offers) live in
lib/draft.py; this module is the page and the pick callback.
"""

import html

import numpy as np
import pandas as pd
import streamlit as st

from core.constants import ARCADE_BUDGET
from dashboard.lib import draft, media, sim
from dashboard.lib import theme as T
from dashboard.lib.data import arcade as arcade_data
from dashboard.views.arcade.team_builder import state as tb_state
from dashboard.views.arcade.team_builder.results import build_results
from dashboard.views.arcade.team_builder.roster import (
    last_team,
    roster_grid,
    slot_label,
    slot_labels,
)


def _option_html(r) -> str:
    team = last_team(r.team)
    tc = T.team_color(team)
    body = (
        f'<div style="display:flex;gap:.8rem;align-items:center">'
        f"{media.avatar_html(int(r.player_id), r.player, size=64, ring=tc)}"
        f'<div style="min-width:0">'
        f'<div class="bip-name" style="font-size:1.05rem;white-space:nowrap;'
        f'overflow:hidden;text-overflow:ellipsis">{html.escape(r.player)}</div>'
        f'<div class="bip-kpi-sub">{r.season} &middot; '
        f'<span style="color:{tc};font-weight:700">{html.escape(team)}</span></div>'
        f"</div></div>"
        f'<div style="display:flex;justify-content:space-between;margin-top:.7rem;'
        f'font-size:.85rem;color:{T.INK_2}">'
        f"<span>{r.ppg:.1f} pts &middot; {r.rpg:.1f} reb &middot; {r.apg:.1f} ast</span>"
        f'<span>Impact <b style="color:{T.INK}">{r.impact:+.2f}</b></span></div>'
    )
    return T.card_html("Option", body, style=f"border-top:3px solid {tc}")


def _new_offer(state: dict, pool: pd.DataFrame) -> None:
    """Three players for the next spot, shown in random order."""
    spot = len(state["picks"])
    if spot >= sim.ROSTER_SIZE:
        state["offer"] = []
        return
    rng = np.random.default_rng()
    labels = draft.offer_options(pool, state["picks"], state["budget"] - state["spent"], spot, rng)
    labels = [labels[i] for i in rng.permutation(len(labels))]
    # pandas-stubs type a .at cell as any scalar, which int() rejects.
    state["offer"] = [(int(pool.at[lb, "player_id"]), str(pool.at[lb, "season"])) for lb in labels]  # type: ignore[arg-type]


def _start_pick_draft(pool: pd.DataFrame, choice: str) -> dict:
    state = draft.new_pick_draft(np.random.default_rng())
    state.update(pool=choice, spent=0)
    _new_offer(state, pool)
    st.session_state[tb_state.PICK] = state
    return state


def _tb_pick(season: str | None, key: tuple[int, str]) -> None:
    state = st.session_state.get(tb_state.PICK)
    if state is None or key not in state["offer"]:
        return  # a stale click: a double click, or the offer already moved on
    pool = arcade_data.player_impact_pool(season)
    label = slot_labels(pool, [key])[0]
    if label is None:
        return
    state["picks"].append(key)
    state["spent"] += int(pool.at[label, "cost"])  # type: ignore[arg-type]  # .at cell, see _new_offer
    _new_offer(state, pool)


def render_draft(pool: pd.DataFrame, season: str | None, choice: str, meta) -> None:
    state = st.session_state.get(tb_state.PICK)
    if state is None or state.get("pool") != choice:
        state = _start_pick_draft(pool, choice)
    spot = len(state["picks"])
    labels = slot_labels(pool, state["picks"] + [None] * (sim.ROSTER_SIZE - spot))

    if spot < sim.ROSTER_SIZE:
        offer = slot_labels(pool, state["offer"])
        if all(lb is None for lb in offer):  # e.g. the data was refreshed mid-draft
            _new_offer(state, pool)
            offer = slot_labels(pool, state["offer"])
        st.caption(
            "Eight rounds, one for each spot on your team: pick one of three "
            "players each round. A hidden budget decides who gets offered, so "
            "taking a star now means cheaper options later. Some drafts draw "
            "a bigger budget than others - that's the luck."
        )
        st.markdown(
            f"{T.chip(f'Round {spot + 1} of {sim.ROSTER_SIZE}')} &nbsp;"
            f"Pick your **{slot_label(spot)}**",
            unsafe_allow_html=True,
        )
        cols = st.columns(draft.OPTIONS)
        # The offer can hold fewer than OPTIONS players when the pool runs low,
        # so index the columns rather than zipping them.
        for k, (key, label) in enumerate(zip(state["offer"], offer, strict=True)):
            if label is None:
                continue
            with cols[k]:
                st.markdown(_option_html(pool.loc[label]), unsafe_allow_html=True)
                st.button(
                    "Pick him",
                    key=f"tb_pick_{k}",
                    type="primary",
                    width="stretch",
                    on_click=_tb_pick,
                    args=(season, key),
                )
        st.markdown("#### Your team")
        roster_grid(pool, labels, spot)
        return

    roster_grid(pool, labels, None)
    rows = pool.loc[[lb for lb in labels if lb is not None]]
    st.caption(
        f"Your hidden budget was **{state['budget']} credits** (every draft "
        f"draws {draft.DRAFT_BUDGET_MIN}-{draft.DRAFT_BUDGET_MAX}); this team "
        f"cost {state['spent']}. Build mode prices every player and gives "
        f"everyone {ARCADE_BUDGET}."
    )
    st.button("Draft again", key="tb_pick_again", on_click=tb_state.reset)
    if len(rows) == sim.ROSTER_SIZE:
        build_results(rows, season, choice, meta, mode="draft")
