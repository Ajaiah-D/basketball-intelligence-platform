"""The Standings tab: the season's table by conference or league-wide."""

from typing import Any

import pandas as pd
import streamlit as st

from dashboard.lib import glossary
from dashboard.lib import theme as T


def form_dots(form: str) -> str:
    return "".join(
        f'<span class="dot dot-{"w" if ch == "W" else "l"}"></span>'
        for ch in reversed(form)  # oldest to newest, newest dot last
    )


def standings_table(df: pd.DataFrame) -> str:
    def th(label: str, term: str) -> str:
        return f"{label}{T.tip(glossary.TERMS[term])}"

    head = (
        '<table class="bip-table"><tr><th class="lft">#</th><th class="lft">Team</th>'
        f"<th>W</th><th>L</th><th>{th('PCT', 'PCT')}</th><th>PTS</th>"
        f"<th>{th('OPP', 'OPP')}</th><th>{th('+/-', 'Team +/-')}</th>"
        '<th style="text-align:left;padding-left:.8rem">'
        f"{th('Form', 'Form')}</th></tr>"
    )
    rows = []
    r: Any  # itertuples() rows: pandas-stubs types each field as any scalar
    for i, r in enumerate(df.itertuples(), 1):
        diff_cls = "pos" if r.net > 0 else ("neg" if r.net < 0 else "")
        rows.append(
            f'<tr><td class="lft">{i}</td>'
            f'<td class="lft tm">{T.team_dot(r.team)}{r.team_name}</td>'
            f"<td>{r.w}</td><td>{r.l}</td><td>{r.pct:.3f}</td>"
            f"<td>{r.ppg:.1f}</td><td>{r.opp_ppg:.1f}</td>"
            f'<td class="{diff_cls}">{r.net:+.1f}</td>'
            f'<td style="text-align:left;padding-left:.8rem">{form_dots(r.form)}</td></tr>'
        )
    return head + "".join(rows) + "</table>"


def render_standings(standings: pd.DataFrame) -> None:
    """The tab: a conference switch over the season's standings."""
    conf = (
        st.segmented_control(
            "Conference",
            ["Eastern", "Western", "League"],
            default="Eastern",
            label_visibility="collapsed",
            key="standings_conf",
        )
        or "Eastern"
    )
    shown = {
        "Eastern": standings[standings.conf == "East"],
        "Western": standings[standings.conf == "West"],
        "League": standings,
    }[conf]
    st.markdown(f'<div class="bip-card">{standings_table(shown)}</div>', unsafe_allow_html=True)
    st.caption("Form shows the last five games, most recent on the right.")
