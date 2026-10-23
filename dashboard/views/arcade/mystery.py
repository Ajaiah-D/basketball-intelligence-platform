"""Mystery Player: identify a notable player-season from progressive clues.

Session state: GAME (the hidden row, the guesses so far, done and won
flags), DIFFICULTY (the segmented control) and PICK (the guess selectbox).
"""

import pandas as pd
import streamlit as st

from core import teams
from dashboard.lib.data import arcade as arcade_data
from dashboard.views.arcade.cards import player_card

# Session-state keys.
GAME = "my"
DIFFICULTY = "my_difficulty"
PICK = "my_pick"

MAX_GUESSES = 6
DIFFICULTIES = {
    "Legends (easier)": 24.0,  # superstar seasons only - famous names
    "All-Stars (harder)": 18.0,
}
DEFAULT_DIFFICULTY = "Legends (easier)"


def my_new_game() -> None:
    pool = arcade_data.arcade_pool()
    min_ppg = DIFFICULTIES[st.session_state.get(DIFFICULTY, DEFAULT_DIFFICULTY)]
    stars = pool[pool.ppg >= min_ppg]
    st.session_state[GAME] = {
        "row": stars.sample(1).iloc[0],
        "guesses": [],
        "done": False,
        "won": False,
    }


def archetype(r) -> str:
    """Rough stat-profile label so the opening clue narrows the field."""
    if r.bpg >= 1.8 or (r.rpg >= 10 and r.apg < 4):
        role = "big man"
    elif r.apg >= 6.5:
        role = "playmaker"
    elif r.rpg >= 6.5:
        role = "do-it-all forward"
    else:
        role = "scoring guard/wing"
    volume = (
        "high-volume three-point shooter"
        if r.tpa_pg == r.tpa_pg and r.tpa_pg >= 6
        else (
            "rarely shot threes"
            if r.tpa_pg != r.tpa_pg or r.tpa_pg < 1.5
            else "moderate three-point volume"
        )
    )
    return f"{role}, {volume}"


def my_clues(r) -> list[str]:
    """Clue strings are rendered inside raw HTML cards, so emphasis must be
    HTML tags - markdown syntax like **bold** is NOT processed there."""
    decade = f"{r.season[:3]}0s"
    tier = "30+" if r.ppg >= 30 else "25+" if r.ppg >= 25 else "20+" if r.ppg >= 20 else "under 20"
    # Age (when known - see arcade_data.arcade_pool) leads the first clue: it
    # frames everything after it, a 21-year-old and a 34-year-old are
    # different hunts.
    age = r.get("age")
    who = f"<b>{int(age)}-year-old</b> " if age is not None and pd.notna(age) else ""
    opener = (
        f"A {who}<b>{decade}</b> {teams.conference(r.team, r.season)} player &middot; "
        f"profile: <b>{archetype(r)}</b> &middot; scored "
        f"<b>{tier} a game</b> that season"
    )
    box = f"Stat line: <b>{r.ppg:.1f} pts / {r.rpg:.1f} reb / {r.apg:.1f} ast</b> in {r.gp} games"
    three = (
        f"Threes: <b>{r.tpg:.1f} made on {r.tpa_pg:.1f} attempts/game</b>"
        if r.tpa_pg == r.tpa_pg
        else "Threes: barely attempted any"
    )
    splits = (
        f"Shooting: <b>{r.fg_pct:.1f} FG% / {r.ft_pct:.1f} FT%</b> &middot; "
        f"defense: {r.spg:.1f} stl, {r.bpg:.1f} blk"
    )
    team = f"Team: <b>{r.team}</b> &middot; exact season: <b>{r.season}</b>"
    letter = f"Last name starts with <b>{r.player.split()[-1][0]}</b>"
    return [opener, box, three, splits, team, letter]


def my_guess() -> None:
    g = st.session_state[GAME]
    name = st.session_state.get(PICK, "")
    if g["done"] or not name:
        return
    g["guesses"].append(name)
    if name == g["row"].player:
        g["done"], g["won"] = True, True
    elif len(g["guesses"]) >= MAX_GUESSES:
        g["done"] = True


def render_mystery() -> None:
    if GAME not in st.session_state:
        my_new_game()
    g = st.session_state[GAME]
    r = g["row"]
    clues = my_clues(r)
    wrong = len([x for x in g["guesses"] if x != r.player])

    st.markdown("#### Guess the player-season")
    d1, _ = st.columns([2, 3])
    d1.segmented_control(
        "Difficulty",
        list(DIFFICULTIES),
        key=DIFFICULTY,
        default=DEFAULT_DIFFICULTY,
        label_visibility="collapsed",
        on_change=my_new_game,
    )
    st.caption(
        f"A notable season from any year since 1979-80. Each wrong guess "
        f"reveals another clue - {MAX_GUESSES} guesses total. "
        f"Legends mode sticks to famous superstar seasons."
    )

    shown = clues[: wrong + 1]
    st.markdown(
        '<div class="bip-card">'
        + "".join(
            f'<div class="bip-row"><span class="bip-rank">{i}</span>'
            f'<span class="bip-name" style="white-space:normal">{c}</span></div>'
            for i, c in enumerate(shown, 1)
        )
        + "</div>",
        unsafe_allow_html=True,
    )

    if g["guesses"]:
        st.caption(
            "Guesses: "
            + "  |  ".join(
                ("~~" + x + "~~" if x != r.player else "**" + x + "**") for x in g["guesses"]
            )
        )

    if not g["done"]:
        names = sorted(arcade_data.arcade_pool()["player"].unique())
        st.selectbox(
            "Your guess",
            ["", *names],
            key=PICK,
            label_visibility="collapsed",
            placeholder="Type to search players...",
        )
        c1, c2, _ = st.columns([1, 1, 3])
        c1.button("Guess", type="primary", width="stretch", on_click=my_guess)
        c2.button(
            "Give up", width="stretch", on_click=lambda: st.session_state[GAME].update(done=True)
        )
    else:
        st.markdown(player_card(r), unsafe_allow_html=True)
        if g["won"]:
            st.success(
                f"Got it in {len(g['guesses'])} - **{r.player}**, "
                f"{r.season} {r.team}: {r.ppg:.1f}/{r.rpg:.1f}/{r.apg:.1f}"
            )
            st.balloons()
        else:
            st.error(
                f"It was **{r.player}** - {r.season} {r.team}: {r.ppg:.1f}/{r.rpg:.1f}/{r.apg:.1f}"
            )
        st.button("New mystery", type="primary", on_click=my_new_game)
