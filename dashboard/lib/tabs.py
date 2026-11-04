"""Tabs whose selection lives in session state.

st.tabs runs every tab's body on every rerun unless it tracks state, and a
page like Players has three tabs that each query the warehouse, so only the
active tab should render. keyed_tabs draws the tabs with state tracking on
and hands back the active label; callers put just that tab's body inside
`containers[active]`.

Opening a tab from somewhere else (a search pick, a table row, a link from
the Teams page) goes through open_tab. Streamlit refuses to write a widget's
session-state key once the widget has been drawn in the same run, and the
picker that triggers the open usually sits inside a tab body, below the
tabs. So open_tab writes the label under f"{key}__next" instead, and
keyed_tabs moves it into `key` just before drawing, which Streamlit allows
and which selects that tab in the browser. In a widget callback (on_click,
on_change) the rerun is automatic; called from the page body, follow it with
st.rerun() so the tabs are drawn again with the new selection.
"""

from __future__ import annotations

import streamlit as st
from streamlit.delta_generator import DeltaGenerator


def _next_key(key: str) -> str:
    return f"{key}__next"


def keyed_tabs(labels: list[str], key: str) -> tuple[str, dict[str, DeltaGenerator]]:
    """Draw `labels` as tabs and return (active label, label -> container).

    The selection is kept in st.session_state[key]. The first run opens
    `labels[0]`; a label queued by open_tab wins over what is stored; a
    stored label that is no longer one of `labels` (a tab that disappeared
    for this player or season) falls back to the first tab.
    """
    queued = st.session_state.pop(_next_key(key), None)
    if queued in labels:
        st.session_state[key] = queued
    current = st.session_state.get(key)
    if current is not None and current not in labels:
        del st.session_state[key]
        current = None
    default = current if current is not None else labels[0]

    containers = st.tabs(labels, key=key, on_change="rerun", default=default)
    # `.open` is the widget's own state for this run, so it agrees with what
    # the browser shows even on the run where the user clicked a tab.
    active = next(
        (label for label, tab in zip(labels, containers, strict=True) if tab.open), labels[0]
    )
    by_label: dict[str, DeltaGenerator] = dict(zip(labels, containers, strict=True))
    return active, by_label


def open_tab(key: str, label: str) -> None:
    """Make the next run of keyed_tabs(..., key) open the tab `label`."""
    st.session_state[_next_key(key)] = label
