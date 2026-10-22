"""The roster grid both team-builder modes show: slot labels, the eight spot
cards (five starters over three bench), and the helpers that map a roster of
(player_id, season) pairs onto the pool. Build passes its click callbacks to
make the grid editable; Draft shows it read-only.
"""

import html
from collections.abc import Callable

import pandas as pd
import streamlit as st

from dashboard.lib import media, sim
from dashboard.lib import theme as T


def last_team(path: str) -> str:
    """'CHI → BOS' -> 'BOS', the team he finished the season with."""
    return str(path).split("→")[-1].strip()


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
    pool: pd.DataFrame,
    labels: list,
    target: int | None,
    on_remove: Callable[[int], None] | None = None,
    on_target: Callable[[int], None] | None = None,
) -> None:
    """The eight spots, five starters over three bench. Editable (Build
    mode) when the callbacks are given: each spot has one button, Remove
    (`on_remove`) when filled, or pick that spot for the next player
    (`on_target`). Without them (Draft mode) the grid is read-only and
    hides prices."""
    editable = on_remove is not None and on_target is not None
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
                        "Remove", key=f"tb_rm_{i}", width="stretch", on_click=on_remove, args=(i,)
                    )
                elif i == target:
                    st.button("Picking here", key=f"tb_slot_{i}", width="stretch", disabled=True)
                else:
                    st.button(
                        "Pick for this spot",
                        key=f"tb_slot_{i}",
                        width="stretch",
                        on_click=on_target,
                        args=(i,),
                    )
