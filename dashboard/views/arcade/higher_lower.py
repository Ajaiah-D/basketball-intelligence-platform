"""Higher or Lower: two player-seasons from any era, guess who averaged more.

Session state: "hl" (the round: both rows, the stat, phase "guess" or
"reveal", whether the guess was right), "hl_streak" and "hl_best" (the run
of correct guesses and the best run this session); the pick buttons are
"hl_a" and "hl_b".
"""

import random

import pandas as pd
import streamlit as st

from dashboard.lib import theme as T
from dashboard.lib.data import arcade as arcade_data
from dashboard.views.arcade.cards import player_card, stat_html

STATS = {
    "ppg": ("points", "PPG"),
    "rpg": ("rebounds", "RPG"),
    "apg": ("assists", "APG"),
    "tpg": ("threes made", "3PM/game"),
}


def hl_new_round() -> None:
    pool = arcade_data.arcade_pool()
    stat = random.choice(list(STATS))
    # pick two seasons with meaningfully different values so rounds are fair
    for _ in range(50):
        pair = pool.sample(2)
        a, b = pair.iloc[0], pair.iloc[1]
        if abs(a[stat] - b[stat]) >= 0.6:
            break
    st.session_state.hl = {"a": a, "b": b, "stat": stat, "phase": "guess", "correct": None}


def hl_pick(side: str) -> None:
    g = st.session_state.hl
    a, b, stat = g["a"], g["b"], g["stat"]
    picked, other = (a, b) if side == "a" else (b, a)
    correct = picked[stat] >= other[stat]
    g["phase"] = "reveal"
    g["correct"] = correct
    if correct:
        st.session_state.hl_streak = st.session_state.get("hl_streak", 0) + 1
        st.session_state.hl_best = max(
            st.session_state.get("hl_best", 0), st.session_state.hl_streak
        )
    else:
        st.session_state.hl_streak = 0


def render_higher_lower() -> None:
    if "hl" not in st.session_state:
        hl_new_round()
    g = st.session_state.hl
    a, b, stat = g["a"], g["b"], g["stat"]
    noun, label = STATS[stat]

    s1, s2, _ = st.columns([1, 1, 3])
    s1.markdown(T.kpi("Streak", str(st.session_state.get("hl_streak", 0))), unsafe_allow_html=True)
    s2.markdown(T.kpi("Best", str(st.session_state.get("hl_best", 0))), unsafe_allow_html=True)

    st.markdown(f"#### Who averaged more **{noun}** ({label})?")
    if pd.notna(a.get("age")) or pd.notna(b.get("age")):
        st.caption("Ages are the NBA's, as of the end of that season.")
    c1, c2 = st.columns(2)
    if g["phase"] == "guess":
        # The "?" holds the stat's place, so the cards keep their height
        # when the answer appears.
        with c1:
            st.markdown(player_card(a, stat_html("?", label, T.MUTED)), unsafe_allow_html=True)
            st.button(
                f"Pick {a.player}", key="hl_a", width="stretch", on_click=hl_pick, args=("a",)
            )
        with c2:
            st.markdown(player_card(b, stat_html("?", label, T.MUTED)), unsafe_allow_html=True)
            st.button(
                f"Pick {b.player}", key="hl_b", width="stretch", on_click=hl_pick, args=("b",)
            )
    else:
        winner_is_a = a[stat] >= b[stat]
        for col, r, won in ((c1, a, winner_is_a), (c2, b, not winner_is_a)):
            col.markdown(
                player_card(r, stat_html(f"{r[stat]:.1f}", label, T.GOOD if won else T.MUTED)),
                unsafe_allow_html=True,
            )
        if g["correct"]:
            st.success(f"Correct! Streak: {st.session_state.hl_streak}")
        else:
            st.error(
                f"Wrong - streak over. Best this session: {st.session_state.get('hl_best', 0)}"
            )
        st.button("Next matchup", type="primary", on_click=hl_new_round)
