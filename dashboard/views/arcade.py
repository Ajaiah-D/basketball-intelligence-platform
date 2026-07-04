"""Arcade - games built on 47 seasons of real NBA data.

Higher or Lower: two player-seasons from any era, guess who averaged more.
Mystery Player: identify a notable player-season from progressive clues.
"""

import random

import streamlit as st

from dashboard.lib import db, media
from dashboard.lib import theme as T

STATS = {
    "ppg": ("points", "PPG"),
    "rpg": ("rebounds", "RPG"),
    "apg": ("assists", "APG"),
    "tpg": ("threes made", "3PM/game"),
}


def _pool():
    return db.arcade_pool()


def player_card(r, value_html: str = "") -> str:
    tc = T.team_color(r.team)
    return (
        f'<div class="bip-card" style="text-align:center;'
        f'border-top:3px solid {tc}">'
        f'<div style="margin-bottom:.45rem">'
        f'{media.avatar_html(int(r.player_id), r.player, size=76, ring=tc)}</div>'
        f'<div class="bip-kpi-label">{r.season} &middot; '
        f'<span style="color:{tc}">{r.team}</span></div>'
        f'<div class="bip-kpi-value" style="font-size:1.35rem">{r.player}</div>'
        f'{value_html}</div>'
    )


# --- Higher or Lower ------------------------------------------------------------

def hl_new_round() -> None:
    pool = _pool()
    stat = random.choice(list(STATS))
    # pick two seasons with meaningfully different values so rounds are fair
    for _ in range(50):
        pair = pool.sample(2)
        a, b = pair.iloc[0], pair.iloc[1]
        if abs(a[stat] - b[stat]) >= 0.6:
            break
    st.session_state.hl = {"a": a, "b": b, "stat": stat, "phase": "guess",
                           "correct": None}


def hl_pick(side: str) -> None:
    g = st.session_state.hl
    a, b, stat = g["a"], g["b"], g["stat"]
    picked, other = (a, b) if side == "a" else (b, a)
    correct = picked[stat] >= other[stat]
    g["phase"] = "reveal"
    g["correct"] = correct
    if correct:
        st.session_state.hl_streak = st.session_state.get("hl_streak", 0) + 1
        st.session_state.hl_best = max(st.session_state.get("hl_best", 0),
                                       st.session_state.hl_streak)
    else:
        st.session_state.hl_streak = 0


def render_higher_lower() -> None:
    if "hl" not in st.session_state:
        hl_new_round()
    g = st.session_state.hl
    a, b, stat = g["a"], g["b"], g["stat"]
    noun, label = STATS[stat]

    s1, s2, _ = st.columns([1, 1, 3])
    s1.markdown(T.kpi("Streak", str(st.session_state.get("hl_streak", 0))),
                unsafe_allow_html=True)
    s2.markdown(T.kpi("Best", str(st.session_state.get("hl_best", 0))),
                unsafe_allow_html=True)

    st.markdown(f"#### Who averaged more **{noun}** ({label})?")
    c1, c2 = st.columns(2)
    if g["phase"] == "guess":
        with c1:
            st.markdown(player_card(a), unsafe_allow_html=True)
            st.button(f"Pick {a.player}", key="hl_a", width="stretch",
                      on_click=hl_pick, args=("a",))
        with c2:
            st.markdown(player_card(b), unsafe_allow_html=True)
            st.button(f"Pick {b.player}", key="hl_b", width="stretch",
                      on_click=hl_pick, args=("b",))
    else:
        winner_is_a = a[stat] >= b[stat]
        for col, r, won in ((c1, a, winner_is_a), (c2, b, not winner_is_a)):
            val_color = "#0ca30c" if won else "#898781"
            col.markdown(player_card(
                r, f'<div style="font-size:1.6rem;font-weight:700;'
                   f'color:{val_color}">{r[stat]:.1f} {label}</div>'),
                unsafe_allow_html=True)
        if g["correct"]:
            st.success(f"Correct! Streak: {st.session_state.hl_streak}")
        else:
            st.error(f"Wrong - streak over. Best this session: "
                     f"{st.session_state.get('hl_best', 0)}")
        st.button("Next matchup", type="primary", on_click=hl_new_round)


# --- Mystery Player -------------------------------------------------------------

MAX_GUESSES = 6
DIFFICULTIES = {
    "Legends (easier)": 24.0,   # superstar seasons only - famous names
    "All-Stars (harder)": 18.0,
}


def my_new_game() -> None:
    pool = _pool()
    min_ppg = DIFFICULTIES[st.session_state.get("my_difficulty",
                                                "Legends (easier)")]
    stars = pool[pool.ppg >= min_ppg]
    st.session_state.my = {"row": stars.sample(1).iloc[0], "guesses": [],
                           "done": False, "won": False}


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
    volume = "high-volume three-point shooter" if r.tpa_pg == r.tpa_pg and r.tpa_pg >= 6 \
        else ("rarely shot threes" if r.tpa_pg != r.tpa_pg or r.tpa_pg < 1.5
              else "moderate three-point volume")
    return f"{role}, {volume}"


def my_clues(r) -> list[str]:
    """Clue strings are rendered inside raw HTML cards, so emphasis must be
    HTML tags - markdown syntax like **bold** is NOT processed there."""
    decade = f"{r.season[:3]}0s"
    tier = ('30+' if r.ppg >= 30 else '25+' if r.ppg >= 25
            else '20+' if r.ppg >= 20 else 'under 20')
    opener = (f"A <b>{decade}</b> {db.conference(r.team)} player &middot; "
              f"profile: <b>{archetype(r)}</b> &middot; scored "
              f"<b>{tier} a game</b> that season")
    box = (f"Stat line: <b>{r.ppg:.1f} pts / {r.rpg:.1f} reb / {r.apg:.1f} ast</b> "
           f"in {r.gp} games")
    three = (f"Threes: <b>{r.tpg:.1f} made on {r.tpa_pg:.1f} attempts/game</b>"
             if r.tpa_pg == r.tpa_pg else "Threes: barely attempted any")
    splits = (f"Shooting: <b>{r.fg_pct:.1f} FG% / {r.ft_pct:.1f} FT%</b> &middot; "
              f"defense: {r.spg:.1f} stl, {r.bpg:.1f} blk")
    team = f"Team: <b>{r.team}</b> &middot; exact season: <b>{r.season}</b>"
    letter = f"Last name starts with <b>{r.player.split()[-1][0]}</b>"
    return [opener, box, three, splits, team, letter]


def my_guess() -> None:
    g = st.session_state.my
    name = st.session_state.get("my_pick", "")
    if g["done"] or not name:
        return
    g["guesses"].append(name)
    if name == g["row"].player:
        g["done"], g["won"] = True, True
    elif len(g["guesses"]) >= MAX_GUESSES:
        g["done"] = True


def render_mystery() -> None:
    if "my" not in st.session_state:
        my_new_game()
    g = st.session_state.my
    r = g["row"]
    clues = my_clues(r)
    wrong = len([x for x in g["guesses"] if x != r.player])

    st.markdown("#### Guess the player-season")
    d1, _ = st.columns([2, 3])
    d1.segmented_control("Difficulty", list(DIFFICULTIES), key="my_difficulty",
                         default="Legends (easier)", label_visibility="collapsed",
                         on_change=my_new_game)
    st.caption(f"A notable season from any year since 1979-80. Each wrong guess "
               f"reveals another clue - {MAX_GUESSES} guesses total. "
               f"Legends mode sticks to famous superstar seasons.")

    shown = clues[: wrong + 1]
    st.markdown(
        '<div class="bip-card">' +
        "".join(f'<div class="bip-row"><span class="bip-rank">{i}</span>'
                f'<span class="bip-name" style="white-space:normal">{c}</span></div>'
                for i, c in enumerate(shown, 1)) +
        "</div>",
        unsafe_allow_html=True,
    )

    if g["guesses"]:
        st.caption("Guesses: " + "  |  ".join(
            ("~~" + x + "~~" if x != r.player else "**" + x + "**")
            for x in g["guesses"]))

    if not g["done"]:
        names = sorted(_pool()["player"].unique())
        st.selectbox("Your guess", [""] + names, key="my_pick",
                     label_visibility="collapsed",
                     placeholder="Type to search players...")
        c1, c2, _ = st.columns([1, 1, 3])
        c1.button("Guess", type="primary", width="stretch", on_click=my_guess)
        c2.button("Give up", width="stretch",
                  on_click=lambda: st.session_state.my.update(done=True))
    else:
        st.markdown(player_card(r), unsafe_allow_html=True)
        if g["won"]:
            st.success(f"Got it in {len(g['guesses'])} - **{r.player}**, "
                       f"{r.season} {r.team}: {r.ppg:.1f}/{r.rpg:.1f}/{r.apg:.1f}")
            st.balloons()
        else:
            st.error(f"It was **{r.player}** - {r.season} {r.team}: "
                     f"{r.ppg:.1f}/{r.rpg:.1f}/{r.apg:.1f}")
        st.button("New mystery", type="primary", on_click=my_new_game)


def render() -> None:
    n = len(db.seasons())
    st.markdown(
        f'## Arcade &nbsp;<span class="bip-chip">{n} seasons of data</span>',
        unsafe_allow_html=True,
    )
    tab_hl, tab_my = st.tabs(["Higher or Lower", "Mystery Player"])
    with tab_hl:
        render_higher_lower()
    with tab_my:
        render_mystery()
