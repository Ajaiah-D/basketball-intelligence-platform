"""The Arcade's player-season card (headshot, name, season, team, age) and
the big stat that sits at the bottom of a Higher or Lower card."""

import html

import pandas as pd

from dashboard.lib import media
from dashboard.lib import theme as T


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
