"""Build mode: eight spots (five starters, three bench) filled from a
searchable pool grid under a credit budget, then the shared projection.

Also owns the roster grid and slot cards that Draft mode shows read-only,
and the helpers that map a roster of (player_id, season) pairs onto the pool.
"""

import html
import zlib

import pandas as pd
import streamlit as st

from core.constants import ARCADE_BUDGET, MAX_COST
from core.text import fold
from dashboard.lib import draft, glossary, media, sim
from dashboard.lib import theme as T
from dashboard.views.arcade.team_builder import state as tb_state
from dashboard.views.arcade.team_builder.results import build_results

POOL_ROWS = 200  # the pool grid shows the best 200 matches by impact


def last_team(path: str) -> str:
    """'CHI → BOS' -> 'BOS', the team he finished the season with."""
    return str(path).split("→")[-1].strip()


def _pool_table(pool: pd.DataFrame, exclude):
    """Search box, an empty slot for the caller's action button, and the pool
    grid. Returns (selected row's pool index label or None, the slot). Rows
    in `exclude` (index labels) are left out."""
    query = st.text_input(
        "Search the pool",
        key=tb_state.SEARCH,
        placeholder="Search a name, season or team",
        label_visibility="collapsed",
    )
    bar = st.container()
    avail = pool.loc[~pool.index.isin(list(exclude))]
    tokens = fold(query).split()
    if tokens:
        hay = (avail["player"] + " " + avail["season"] + " " + avail["team"]).map(fold)
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
                format="%d", help=f"Credits he costs in Build mode, 1-{MAX_COST} by impact."
            ),
        },
    )
    more = f" of {len(avail):,}" if len(avail) > len(shown) else ""
    st.caption(f"Showing {len(shown)}{more} by impact. Click a row to select it.")
    rows = list(event.selection.rows) if event is not None else []
    if rows and rows[0] < len(shown):
        return shown.index[rows[0]], bar
    return None, bar


def slot_label(i: int) -> str:
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
    team = last_team(r.team)
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


def roster_grid(
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
                    _slot_html(slot_label(i), r, target=i == target, show_cost=editable),
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
    raw = list(st.session_state.get(tb_state.BUILD_SLOTS) or [])
    raw = (raw + [None] * sim.ROSTER_SIZE)[: sim.ROSTER_SIZE]
    return [None if s is None else (int(s[0]), str(s[1])) for s in raw]


def _target(slots: list) -> int | None:
    """The spot the next pick fills: the one the user chose if it is still
    empty, otherwise the leftmost empty one; None when the team is full."""
    chosen = st.session_state.get(tb_state.SLOT)
    if chosen is not None and 0 <= chosen < len(slots) and slots[chosen] is None:
        return chosen
    return next((i for i, s in enumerate(slots) if s is None), None)


def slot_labels(pool: pd.DataFrame, slots: list) -> list:
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
    st.session_state[tb_state.BUILD_SLOTS] = slots
    st.session_state.pop(tb_state.SLOT, None)
    tb_state.bump()


def _tb_remove(index: int) -> None:
    slots = _slots()
    slots[index] = None
    st.session_state[tb_state.BUILD_SLOTS] = slots
    st.session_state[tb_state.SLOT] = index  # the replacement goes back into this spot
    tb_state.bump()


def _tb_target(index: int) -> None:
    # No bump: a row already selected in the pool table stays selected.
    st.session_state[tb_state.SLOT] = index


def render_build(pool: pd.DataFrame, season: str | None, choice: str, meta) -> None:
    slots = _slots()
    labels = slot_labels(pool, slots)
    target = _target([None if lb is None else s for lb, s in zip(labels, slots, strict=True)])
    rows = pool.loc[[lb for lb in labels if lb is not None]]
    problems = draft.validate_build(rows)
    full = len(rows) >= sim.ROSTER_SIZE
    count_msg = problems[0] if len(rows) != sim.ROSTER_SIZE and problems else ""
    others = problems[1:] if count_msg else problems

    st.caption(
        f"Pick {sim.ROSTER_SIZE} player-seasons with {ARCADE_BUDGET} credits to "
        f"spend; better players cost more (1-{MAX_COST}). The top row starts "
        f"({sim.STARTER_MINUTES} minutes each) and the bottom row comes off the "
        f"bench ({sim.BENCH_MINUTES}). Each pick fills the highlighted spot; "
        f"choose another with its button, or remove a player to replace him."
    )
    used = int(rows["cost"].sum()) if len(rows) else 0
    left = ARCADE_BUDGET - used
    k1, k2, _ = st.columns([1, 1, 3])
    k1.markdown(
        T.kpi(
            "Credits used",
            f"{used} / {ARCADE_BUDGET}",
            sub=f"{left} left" if left >= 0 else f"{-left} over",
        ),
        unsafe_allow_html=True,
    )
    k2.markdown(
        T.kpi("Players", f"{len(rows)} / {sim.ROSTER_SIZE}", sub="5 starters, 3 bench"),
        unsafe_allow_html=True,
    )
    roster_grid(pool, labels, target)
    for msg in others:
        st.warning(msg)

    if not problems:
        build_results(rows, season, choice, meta)
    if not full:
        st.markdown("#### Add players")
        label, bar = _pool_table(pool, exclude=rows.index)
        with bar:
            c1, c2 = st.columns([1, 4], vertical_alignment="center")
            spot = slot_label(target) if target is not None else ""
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
