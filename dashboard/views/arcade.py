"""Arcade - games built on 47 seasons of real NBA data.

Higher or Lower: two player-seasons from any era, guess who averaged more.
Mystery Player: identify a notable player-season from progressive clues.
Build a team: pick eight player-seasons under a budget (Build) or pick one
of three offered players for each spot (Draft), then simulate seasons
(lib/sim.py).

Build a team keeps all of its state in st.session_state under "tb_" keys:
  tb_mode          "Build" | "Draft" (the segmented control)
  tb_pool          "All-time" | a season like "2024-25" (the selectbox)
  tb_search        the pool table's search text
  tb_nonce         int, part of the pool table's widget key; bumped after a
                   pick so the table's row selection starts empty again
  tb_build_slots   Build roster: 8 spots, starters 1-5 then bench 1-3, each
                   a (player_id, season) pair or None. Placement counts: the
                   starter spots play starter minutes
  tb_slot          the spot the user chose for the next pick (index), or
                   absent; an empty chosen spot wins over the leftmost empty
  tb_build_season  {"key": roster key, "result": sim.simulate_season_once,
                   "names": opponent labels} - the last "Simulate a season"
  tb_pick          Draft state from draft.new_pick_draft: "budget" (hidden),
                   "picks" (player_id, season) pairs filling the spots in
                   order, "offer" the three pairs on offer now, plus "spent"
                   credits and "pool", the pool choice it was started with
  tb_proj          {roster key: projection dict} - projections are seeded
                   from the roster, so they are cached per roster
Changing the mode or the pool, or "Start over", clears every one of the game
keys (tb_build_*, tb_slot, tb_pick, tb_proj) and the search.
"""

import html
import random
import unicodedata
import zlib

import numpy as np
import pandas as pd
import streamlit as st

from core import teams
from dashboard.lib import db, draft, glossary, media, sim
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
    """A player-season card read top to bottom: headshot, name, then season,
    team and age on one line under it, then `value_html` (the stat)."""
    tc = T.team_color(r.team)
    meta = [
        f"<span>{r.season}</span>",
        f'<span style="color:{tc};font-weight:800">{T.team_dot(r.team)}{r.team}</span>',
    ]
    age = getattr(r, "age", None)
    if age is not None and not pd.isna(age):
        meta.append(f"<span>age <b>{int(age)}</b></span>")
    return (
        f'<div class="bip-card bip-pc" style="border-top:3px solid {tc}">'
        f"{media.avatar_html(int(r.player_id), r.player, size=88, ring=tc)}"
        f'<div class="bip-pc-name">{html.escape(r.player)}</div>'
        f'<div class="bip-pc-meta">{" <span>&middot;</span> ".join(meta)}</div>'
        f"{value_html}</div>"
    )


def stat_html(value: str, label: str, color: str) -> str:
    """The big stat at the bottom of a Higher or Lower card."""
    return (
        f'<div class="bip-pc-val" style="color:{color}">{value}'
        f'<span class="lbl">{label}</span></div>'
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


# --- Mystery Player -------------------------------------------------------------

MAX_GUESSES = 6
DIFFICULTIES = {
    "Legends (easier)": 24.0,  # superstar seasons only - famous names
    "All-Stars (harder)": 18.0,
}


def my_new_game() -> None:
    pool = _pool()
    min_ppg = DIFFICULTIES[st.session_state.get("my_difficulty", "Legends (easier)")]
    stars = pool[pool.ppg >= min_ppg]
    st.session_state.my = {
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
    # Age (when known - see db.arcade_pool) leads the first clue: it frames
    # everything after it, a 21-year-old and a 34-year-old are different hunts.
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
    d1.segmented_control(
        "Difficulty",
        list(DIFFICULTIES),
        key="my_difficulty",
        default="Legends (easier)",
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
        names = sorted(_pool()["player"].unique())
        st.selectbox(
            "Your guess",
            ["", *names],
            key="my_pick",
            label_visibility="collapsed",
            placeholder="Type to search players...",
        )
        c1, c2, _ = st.columns([1, 1, 3])
        c1.button("Guess", type="primary", width="stretch", on_click=my_guess)
        c2.button(
            "Give up", width="stretch", on_click=lambda: st.session_state.my.update(done=True)
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


# --- Build a team ---------------------------------------------------------------
#
# The numbers come from lib/sim.py (ratings and seasons) and lib/draft.py
# (budget rules and the CPU drafter); this section is only the page. Its
# session_state keys are listed in the module docstring.

ALL_TIME = "All-time"
MODES = ["Build", "Draft"]
POOL_ROWS = 200  # the pool grid shows the best 200 matches by impact
_GAME_KEYS = ("tb_build_slots", "tb_slot", "tb_build_season", "tb_pick", "tb_proj")


def _tb_bump() -> None:
    """New key for the pool grid, so its row selection starts empty."""
    st.session_state["tb_nonce"] = st.session_state.get("tb_nonce", 0) + 1


def _tb_reset() -> None:
    """Clear the game (mode and pool stay as chosen). No confirm step."""
    for key in _GAME_KEYS:
        st.session_state.pop(key, None)
    st.session_state["tb_build_slots"] = [None] * sim.ROSTER_SIZE
    st.session_state["tb_search"] = ""
    _tb_bump()


def _fold(text) -> str:
    """Lower-case, accents dropped, so "jokic" finds "Jokić"."""
    return unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode().lower()


def _last_team(path: str) -> str:
    """'CHI → BOS' -> 'BOS', the team he finished the season with."""
    return str(path).split("→")[-1].strip()


def _pct(p: float) -> str:
    if 0 < p < 0.005:
        return "<1%"
    if 0.995 <= p < 1:
        return ">99%"
    return f"{p:.0%}"


def _rating(net: float) -> float:
    """A rating ready for a one-decimal "%+.1f": anything that would round to
    zero becomes exactly 0.0, so it shows as "+0.0", never "-0.0"."""
    net = float(net)
    return 0.0 if abs(net) < 0.05 else net


def _record(wins: int) -> str:
    return f"{int(wins)}-{sim.SEASON_GAMES - int(wins)}"


def _row_keys(rows: pd.DataFrame) -> list[str]:
    """'player_id:season' per row - the same player in two seasons differs."""
    return [f"{int(p)}:{s}" for p, s in zip(rows["player_id"], rows["season"], strict=True)]


def _meta() -> tuple[float, float, float]:
    """(team_scale, team_offset, usage_league_total) from the impact model."""
    m = db.player_impact_meta()
    return (
        float(m.get("team_scale", 1.0)),
        float(m.get("team_offset", 0.0)),
        float(m.get("usage_league_total", 5.0)),
    )


def _team_net(rows: pd.DataFrame, meta, ordered: bool = False) -> float:
    """Net rating of an 8-man roster. With ordered=True the rows are already
    in rotation order (the first five start); otherwise the best five by
    impact start."""
    rot = rows if ordered else draft.auto_rotation(rows)
    scale, offset, usage_total = meta
    return float(
        sim.team_net_rating(
            rot["impact"], rot["usage"], scale, offset, usage_league_total=usage_total
        )
    )


def _opponents(season: str | None) -> tuple[list[float], list[str], str]:
    """Build mode's league: (net ratings, labels, source).

    source is "season" (that season's real teams), "all-time" (29 real
    team-seasons from 1985-86 on, always the same 29: seed 7; also the
    fallback when a season has no team ratings) or "average" (a placeholder
    average team, for a warehouse with no team ratings at all)."""
    if season is not None:
        teams = db.team_advanced(season)
        teams = teams[teams["net_rating"].notna()].sort_values("team_abbreviation")
        if len(teams) >= 2:
            return (
                teams["net_rating"].astype(float).tolist(),
                teams["team_abbreviation"].tolist(),
                "season",
            )
    every = db.all_team_net_ratings()
    if not len(every):
        return [0.0], ["an average team"], "average"
    idx = np.random.default_rng(7).choice(len(every), size=min(29, len(every)), replace=False)
    drawn = every.iloc[idx]
    return (
        drawn["net_rating"].astype(float).tolist(),
        (drawn["season"] + " " + drawn["team"]).tolist(),
        "all-time",
    )


def _cached(key, compute):
    """Projection cache in session_state; the seed is tied to the roster, so
    a rerun would only recompute the same numbers."""
    cache = st.session_state.setdefault("tb_proj", {})
    if key not in cache:
        if len(cache) > 32:
            cache.clear()
        cache[key] = compute()
    return cache[key]


def _results_row(
    net: float,
    median: int,
    p10: int,
    p90: int,
    odds_label: str,
    odds: float,
    rating_sub: str = "points per 100 vs. an average team",
) -> None:
    c1, c2, c3, c4 = st.columns(4)
    c1.markdown(
        T.kpi(
            "Team rating",
            f"{_rating(net):+.1f}",
            sub=rating_sub,
            help=glossary.TERMS["Team rating"],
        ),
        unsafe_allow_html=True,
    )
    c2.markdown(
        T.kpi(
            "Projected record",
            _record(median),
            sub="median of 1,000 seasons",
            help=glossary.TERMS["Projected record"],
        ),
        unsafe_allow_html=True,
    )
    c3.markdown(
        T.kpi(
            "Range",
            f"{p10}-{p90} wins",
            sub="10th to 90th percentile",
            help=glossary.TERMS["Win range"],
        ),
        unsafe_allow_html=True,
    )
    c4.markdown(
        T.kpi(
            odds_label, _pct(odds), sub="share of 1,000 seasons", help=glossary.TERMS[odds_label]
        ),
        unsafe_allow_html=True,
    )


def _pool_table(pool: pd.DataFrame, exclude):
    """Search box, an empty slot for the caller's action button, and the pool
    grid. Returns (selected row's pool index label or None, the slot). Rows
    in `exclude` (index labels) are left out."""
    query = st.text_input(
        "Search the pool",
        key="tb_search",
        placeholder="Search a name, season or team",
        label_visibility="collapsed",
    )
    bar = st.container()
    avail = pool.loc[~pool.index.isin(list(exclude))]
    tokens = _fold(query).split()
    if tokens:
        hay = (avail["player"] + " " + avail["season"] + " " + avail["team"]).map(_fold)
        mask = pd.Series(True, index=avail.index)
        for tok in tokens:
            mask &= hay.str.contains(tok, regex=False)
        avail = avail[mask]
    shown = avail.head(POOL_ROWS)
    if not len(shown):
        st.caption("No players match that search.")
        return None, bar
    view = pd.DataFrame(
        {
            "Player": shown["player"],
            "Season": shown["season"],
            "Team": shown["team"],
            "GP": shown["gp"],
            "PTS": shown["ppg"],
            "REB": shown["rpg"],
            "AST": shown["apg"],
            "Impact": shown["impact"],
            "Cost": shown["cost"],
        }
    )
    cc = st.column_config
    key = f"tb_table_{st.session_state.get('tb_nonce', 0)}_{zlib.crc32(query.encode('utf-8'))}"
    event = st.dataframe(
        view,
        key=key,
        on_select="rerun",
        selection_mode="single-row",
        hide_index=True,
        width="stretch",
        row_height=38,
        height=min(420, 38 * (len(view) + 1) + 3),
        column_config={
            "GP": cc.NumberColumn(format="%d", **glossary.described("GP")),
            "PTS": cc.NumberColumn(format="%.1f", help="Points per game."),
            "REB": cc.NumberColumn(format="%.1f", help="Rebounds per game."),
            "AST": cc.NumberColumn(format="%.1f", help="Assists per game."),
            "Impact": cc.NumberColumn(format="%+.2f", **glossary.marked("Impact")),
            "Cost": cc.NumberColumn(
                format="%d", help="Credits he costs in Build mode, 1-12 by impact."
            ),
        },
    )
    more = f" of {len(avail):,}" if len(avail) > len(shown) else ""
    st.caption(f"Showing {len(shown)}{more} by impact. Click a row to select it.")
    rows = list(event.selection.rows) if event is not None else []
    if rows and rows[0] < len(shown):
        return shown.index[rows[0]], bar
    return None, bar


def _slot_label(i: int) -> str:
    """'Starter 1'..'Starter 5', then 'Bench 1'..'Bench 3'."""
    if i < sim.STARTERS:
        return f"Starter {i + 1}"
    return f"Bench {i - sim.STARTERS + 1}"


def _slot_html(label: str, r, target: bool = False, show_cost: bool = True) -> str:
    if r is None:
        text, color = ("Next pick goes here", T.ACCENT) if target else ("Empty", T.MUTED)
        body = (
            f'<div style="min-height:76px;display:flex;align-items:center;'
            f'color:{color};font-size:.85rem">{text}</div>'
        )
        style = f"border:1px dashed {T.ACCENT}" if target else ""
        return T.card_html(label, body, style=style)
    team = _last_team(r.team)
    tc = T.team_color(team)
    # Draft mode keeps prices hidden, like its budget.
    cost = f'<span>Cost <b style="color:{T.INK}">{int(r.cost)}</b></span>' if show_cost else ""
    body = (
        f'<div style="min-height:76px">'
        f'<div style="display:flex;gap:.7rem;align-items:center">'
        f"{media.avatar_html(int(r.player_id), r.player, size=46, ring=tc)}"
        f'<div style="min-width:0">'
        f'<div class="bip-name" style="font-size:.95rem">{html.escape(r.player)}</div>'
        f'<div class="bip-kpi-sub">{r.season} &middot; '
        f'<span style="color:{tc};font-weight:700">{html.escape(team)}</span></div>'
        f"</div></div>"
        f'<div style="display:flex;justify-content:space-between;margin-top:.5rem;'
        f'font-size:.8rem;color:{T.INK_2}">'
        f'<span>Impact <b style="color:{T.INK}">{r.impact:+.2f}</b></span>'
        f"{cost}</div></div>"
    )
    return T.card_html(label, body)


def _roster_grid(
    pool: pd.DataFrame, labels: list, target: int | None, editable: bool = True
) -> None:
    """The eight spots, five starters over three bench. Editable (Build
    mode): each spot has one button, Remove when filled, or pick that spot
    for the next player."""
    for start, count in ((0, sim.STARTERS), (sim.STARTERS, sim.ROSTER_SIZE - sim.STARTERS)):
        cols = st.columns(sim.STARTERS)
        for i in range(start, start + count):
            label = labels[i]
            r = pool.loc[label] if label is not None else None
            with cols[i - start]:
                st.markdown(
                    _slot_html(_slot_label(i), r, target=i == target, show_cost=editable),
                    unsafe_allow_html=True,
                )
                if not editable:
                    continue
                if r is not None:
                    st.button(
                        "Remove", key=f"tb_rm_{i}", width="stretch", on_click=_tb_remove, args=(i,)
                    )
                elif i == target:
                    st.button("Picking here", key=f"tb_slot_{i}", width="stretch", disabled=True)
                else:
                    st.button(
                        "Pick for this spot",
                        key=f"tb_slot_{i}",
                        width="stretch",
                        on_click=_tb_target,
                        args=(i,),
                    )


def _slots() -> list[tuple[int, str] | None]:
    """The eight Build spots in order; None is an empty spot."""
    raw = list(st.session_state.get("tb_build_slots") or [])
    raw = (raw + [None] * sim.ROSTER_SIZE)[: sim.ROSTER_SIZE]
    return [None if s is None else (int(s[0]), str(s[1])) for s in raw]


def _target(slots: list) -> int | None:
    """The spot the next pick fills: the one the user chose if it is still
    empty, otherwise the leftmost empty one; None when the team is full."""
    chosen = st.session_state.get("tb_slot")
    if chosen is not None and 0 <= chosen < len(slots) and slots[chosen] is None:
        return chosen
    return next((i for i, s in enumerate(slots) if s is None), None)


def _slot_labels(pool: pd.DataFrame, slots: list) -> list:
    """Pool index label per spot (None for an empty spot, or for a pick the
    pool no longer has)."""
    ids = [s[0] for s in slots if s is not None]
    cand = pool[pool["player_id"].isin(ids)]
    found = {
        (int(p), str(s)): label
        for label, p, s in zip(cand.index, cand["player_id"], cand["season"], strict=True)
    }
    return [None if s is None else found.get(s) for s in slots]


def _tb_add(key: tuple[int, str]) -> None:
    slots = _slots()
    i = _target(slots)
    if i is not None and key not in slots:
        slots[i] = key
    st.session_state["tb_build_slots"] = slots
    st.session_state.pop("tb_slot", None)
    _tb_bump()


def _tb_remove(index: int) -> None:
    slots = _slots()
    slots[index] = None
    st.session_state["tb_build_slots"] = slots
    st.session_state["tb_slot"] = index  # the replacement goes back into this spot
    _tb_bump()


def _tb_target(index: int) -> None:
    # No bump: a row already selected in the pool table stays selected.
    st.session_state["tb_slot"] = index


def _tb_best_five(order: list[tuple[int, str]], mode: str) -> None:
    if mode == "draft":
        st.session_state["tb_pick"]["picks"] = list(order)
    else:
        st.session_state["tb_build_slots"] = list(order)


def _tb_sim_build(key, net: float, opp_nets: list[float], names: list[str]) -> None:
    st.session_state["tb_build_season"] = {
        "key": key,
        "names": names,
        "result": sim.simulate_season_once(net, opp_nets, np.random.default_rng()),
    }


def _streaks(results: list[bool]) -> tuple[int, int]:
    """(longest winning streak, longest losing streak)."""
    best = worst = run = 0
    prev = None
    for won in results:
        run = run + 1 if won == prev else 1
        prev = won
        if won:
            best = max(best, run)
        else:
            worst = max(worst, run)
    return best, worst


def _season_card(season: dict) -> str:
    res, names = season["result"], season["names"]
    dots = []
    for k, (opp, home, margin, won) in enumerate(res["games"]):
        title = (
            f"Game {k + 1}: {'vs' if home else 'at'} {names[opp]} - "
            f"{'won' if won else 'lost'} by {max(1, round(abs(margin)))}"
        )
        dots.append(
            f'<span class="dot {"dot-w" if won else "dot-l"}" '
            f'title="{html.escape(title, quote=True)}" style="border-radius:1px;'
            f'width:10px;height:10px;margin:0 2px 3px 0"></span>'
        )
    best, worst = _streaks([g[3] for g in res["games"]])
    body = (
        f'<div class="bip-kpi-value">{res["wins"]}-{res["losses"]}</div>'
        f'<div style="display:flex;flex-wrap:wrap;margin:.6rem 0 .45rem">'
        f"{''.join(dots)}</div>"
        f'<div class="bip-kpi-sub">Longest winning streak <b>{best}</b> &middot; '
        f"longest losing streak <b>{worst}</b> &middot; green is a win, red a loss; "
        f"hover a square for the game</div>"
    )
    return T.card_html("One simulated season", body)


def _build_results(
    rows: pd.DataFrame, season: str | None, choice: str, meta, mode: str = "build"
) -> None:
    """Projection for a full roster against real teams (both modes); `rows`
    are in spot order, so the first five are the starters."""
    keys = _row_keys(rows)
    starters, bench = keys[: sim.STARTERS], keys[sim.STARTERS :]
    # The linear calibration would rate a roster of eight star seasons far
    # past any real team; past +10 the soft ceiling keeps it near the best
    # ever (anything up to +10 is left as is).
    net = sim.soft_cap(_team_net(rows, meta, ordered=True))
    opp_nets, opp_names, source = _opponents(season)
    # Order within the starters (or the bench) doesn't change the minutes.
    cache_key = (mode, choice, tuple(sorted(starters)), tuple(sorted(bench)))

    def project() -> dict:
        res = sim.simulate_vs_league(net, opp_nets, np.random.default_rng(sim.roster_seed(keys)))
        return {k: res[k] for k in ("median", "p10", "p90", "best_record_odds")}

    proj = _cached(cache_key, project)
    st.markdown("#### Projection")
    _results_row(
        net, proj["median"], proj["p10"], proj["p90"], "Best-record odds", proj["best_record_odds"]
    )
    _best_five_hint(rows, net, meta, mode)
    if source == "season":
        against = (
            f"82 games against {season}'s {len(opp_nets)} real teams, each at its real net rating."
        )
    elif source == "all-time":
        lead = f"{season} has no team ratings, so it's " if season is not None else ""
        against = (
            f"{lead}82 games against {len(opp_nets)} real team-seasons drawn "
            f"from 1985-86 on, each at its real net rating."
        )
    else:
        against = (
            "82 games against an average team - this copy of the data has no team ratings yet."
        )
    st.caption(against)
    st.button(
        "Simulate a season",
        key="tb_build_sim",
        type="primary",
        on_click=_tb_sim_build,
        args=(cache_key, net, opp_nets, opp_names),
    )
    played = st.session_state.get("tb_build_season")
    if played and played["key"] == cache_key:
        st.markdown(_season_card(played), unsafe_allow_html=True)


def _best_five_hint(rows: pd.DataFrame, net: float, meta, mode: str) -> None:
    """One-click fix when starting the five best impacts would rate higher."""
    best = draft.auto_rotation(rows)
    best_net = sim.soft_cap(_team_net(best, meta, ordered=True))
    gain = best_net - net
    if gain < 0.05:
        return
    c1, c2 = st.columns([1, 4], vertical_alignment="center")
    c1.button(
        "Start the best five",
        key="tb_best_five",
        width="stretch",
        on_click=_tb_best_five,
        args=(
            [(int(p), str(s)) for p, s in zip(best["player_id"], best["season"], strict=True)],
            mode,
        ),
    )
    c2.caption(
        f"Some of your best players are on the bench. Starting the five "
        f"highest impacts would raise the team rating by {gain:.1f}."
    )


def _render_build(pool: pd.DataFrame, season: str | None, choice: str, meta) -> None:
    slots = _slots()
    labels = _slot_labels(pool, slots)
    target = _target([None if lb is None else s for lb, s in zip(labels, slots, strict=True)])
    rows = pool.loc[[lb for lb in labels if lb is not None]]
    problems = draft.validate_build(rows)
    full = len(rows) >= sim.ROSTER_SIZE
    count_msg = problems[0] if len(rows) != sim.ROSTER_SIZE and problems else ""
    others = problems[1:] if count_msg else problems

    st.caption(
        f"Pick {sim.ROSTER_SIZE} player-seasons with {draft.BUDGET} credits to "
        f"spend; better players cost more (1-12). The top row starts "
        f"({sim.STARTER_MINUTES} minutes each) and the bottom row comes off the "
        f"bench ({sim.BENCH_MINUTES}). Each pick fills the highlighted spot; "
        f"choose another with its button, or remove a player to replace him."
    )
    used = int(rows["cost"].sum()) if len(rows) else 0
    left = draft.BUDGET - used
    k1, k2, _ = st.columns([1, 1, 3])
    k1.markdown(
        T.kpi(
            "Credits used",
            f"{used} / {draft.BUDGET}",
            sub=f"{left} left" if left >= 0 else f"{-left} over",
        ),
        unsafe_allow_html=True,
    )
    k2.markdown(
        T.kpi("Players", f"{len(rows)} / {sim.ROSTER_SIZE}", sub="5 starters, 3 bench"),
        unsafe_allow_html=True,
    )
    _roster_grid(pool, labels, target)
    for msg in others:
        st.warning(msg)

    if not problems:
        _build_results(rows, season, choice, meta)
    if not full:
        st.markdown("#### Add players")
        label, bar = _pool_table(pool, exclude=rows.index)
        with bar:
            c1, c2 = st.columns([1, 4], vertical_alignment="center")
            spot = _slot_label(target) if target is not None else ""
            if label is not None:
                r = pool.loc[label]
                note = (
                    f"Selected: **{r.player}**, {r.season} "
                    f"({int(r.cost)} credits), into {spot}. {count_msg}"
                )
                key = (int(r.player_id), str(r.season))
            else:
                note, key = (
                    (f"Select a row in the table, then add him to {spot}. {count_msg}"),
                    None,
                )
            c1.button(
                "Add to team",
                key="tb_add",
                type="primary",
                width="stretch",
                disabled=key is None,
                on_click=_tb_add,
                args=(key,),
            )
            c2.caption(note)


# Draft mode


def _option_html(r) -> str:
    team = _last_team(r.team)
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
    st.session_state["tb_pick"] = state
    return state


def _tb_pick(season: str | None, key: tuple[int, str]) -> None:
    state = st.session_state.get("tb_pick")
    if state is None or key not in state["offer"]:
        return  # a stale click: a double click, or the offer already moved on
    pool = db.player_impact_pool(season)
    label = _slot_labels(pool, [key])[0]
    if label is None:
        return
    state["picks"].append(key)
    state["spent"] += int(pool.at[label, "cost"])  # type: ignore[arg-type]  # .at cell, see _new_offer
    _new_offer(state, pool)


def _render_draft(pool: pd.DataFrame, season: str | None, choice: str, meta) -> None:
    state = st.session_state.get("tb_pick")
    if state is None or state.get("pool") != choice:
        state = _start_pick_draft(pool, choice)
    spot = len(state["picks"])
    labels = _slot_labels(pool, state["picks"] + [None] * (sim.ROSTER_SIZE - spot))

    if spot < sim.ROSTER_SIZE:
        offer = _slot_labels(pool, state["offer"])
        if all(lb is None for lb in offer):  # e.g. the data was refreshed mid-draft
            _new_offer(state, pool)
            offer = _slot_labels(pool, state["offer"])
        st.caption(
            "Eight rounds, one for each spot on your team: pick one of three "
            "players each round. A hidden budget decides who gets offered, so "
            "taking a star now means cheaper options later. Some drafts draw "
            "a bigger budget than others - that's the luck."
        )
        st.markdown(
            f"{T.chip(f'Round {spot + 1} of {sim.ROSTER_SIZE}')} &nbsp;"
            f"Pick your **{_slot_label(spot)}**",
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
        _roster_grid(pool, labels, spot, editable=False)
        return

    _roster_grid(pool, labels, None, editable=False)
    rows = pool.loc[[lb for lb in labels if lb is not None]]
    st.caption(
        f"Your hidden budget was **{state['budget']} credits** (every draft "
        f"draws {draft.DRAFT_BUDGET_MIN}-{draft.DRAFT_BUDGET_MAX}); this team "
        f"cost {state['spent']}. Build mode prices every player and gives "
        f"everyone {draft.BUDGET}."
    )
    st.button("Draft again", key="tb_pick_again", on_click=_tb_reset)
    if len(rows) == sim.ROSTER_SIZE:
        _build_results(rows, season, choice, meta, mode="draft")


def _explainer(meta_row: dict) -> None:
    r2 = meta_row.get("team_r2")
    fit = (
        f" On real team-seasons the conversion explains {float(r2):.0%} of the "
        f"spread in net rating."
        if r2 is not None and r2 == r2
        else ""
    )
    with st.expander("How the simulation works"):
        st.markdown(
            f"""
**Impact.** Every player-season since 1985-86 gets one number: points, rebounds,
assists, steals, blocks, turnovers, shots and fouls per 36 minutes, each weighed by
a model fit to how much players' teams outscored opponents while they were on the
court. 0 is a typical rotation player; the best seasons ever reach about +5 to +6.

**Era adjustment.** Every rate is compared with that season's league average
before it's weighed, so a 1988 rebounder and a 2024 shooter are rated on the same
scale. That's what makes an all-time team possible.

**Minutes.** Your top row starts and plays {sim.STARTER_MINUTES} minutes; the
three bench players play {sim.BENCH_MINUTES} (5 × {sim.STARTER_MINUTES} + 3 ×
{sim.BENCH_MINUTES} = 240, one game's worth of player-minutes). Impact weighted by
those minutes becomes the team rating.{fit}

**Usage overlap.** There's only one ball. When a lineup's combined usage (shots,
free throws and turnovers) runs past what a normal lineup carries, part of its
positive impact is lost. This rule is a rough heuristic, not fitted to data.

**Game randomness.** Each game's margin is the rating gap, plus {sim.HOME_EDGE}
points for the home team, plus random noise of ±{sim.GAME_SD} points (one standard
deviation, as measured on real NBA games). Good teams lose plenty of single games.

**A ceiling.** Real teams top out around +13 (the 1995-96 Bulls). A rating up to
+{sim.ABS_NET_KNEE:.0f} is shown exactly as computed; past that, a stacked roster's
rating bends smoothly toward a +{sim.ABS_NET_CAP:.0f} ceiling instead of running off
the chart. Projections can shift slightly when the weekly data refresh updates the
current season.

**Draft mode's hidden budget.** Every player-season has a price, 1 to 12 credits
by impact (Build mode shows it). A draft secretly gets
{draft.DRAFT_BUDGET_MIN}-{draft.DRAFT_BUDGET_MAX} credits, and each round offers one
pricier, one fair and one cheaper player for that spot, so whatever you pick, the
team ends up about as strong as the budget allows. A bigger budget is the lucky
draft.

**Same team, same projection.** The projection plays 1,000 seasons from a seed tied
to your roster, so the same eight players always get the same numbers. "Simulate a
season" plays one fresh season, so each one comes out differently.

It's a game built on real numbers, not a scouting tool.
"""
        )


def render_build_team() -> None:
    if not db.player_impact_available():
        st.info("Team building needs a newer copy of the data - check back after the next refresh.")
        return
    all_pool = db.player_impact_pool(None)
    choices = [ALL_TIME, *sorted((str(s) for s in all_pool["season"].unique()), reverse=True)]
    if st.session_state.get("tb_mode") not in MODES:
        st.session_state["tb_mode"] = MODES[0]
    if st.session_state.get("tb_pool") not in choices:
        st.session_state["tb_pool"] = ALL_TIME

    c1, c2, c3, _ = st.columns([1.1, 1.3, 0.8, 2.8], vertical_alignment="bottom")
    c1.segmented_control("Mode", MODES, key="tb_mode", required=True, on_change=_tb_reset)
    c2.selectbox("Player pool", choices, key="tb_pool", on_change=_tb_reset)
    c3.button("Start over", key="tb_restart", width="stretch", on_click=_tb_reset)

    choice = st.session_state["tb_pool"]
    season = None if choice == ALL_TIME else choice
    pool = all_pool if season is None else db.player_impact_pool(season)
    meta = _meta()
    if st.session_state["tb_mode"] == "Build":
        _render_build(pool, season, choice, meta)
    else:
        _render_draft(pool, season, choice, meta)
    _explainer(db.player_impact_meta())


def render() -> None:
    n = len(db.seasons())
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
