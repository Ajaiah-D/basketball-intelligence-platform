"""Widget state the Players and Teams pages share: a keyed choice that
always holds one of its options, choices held while their tab isn't drawn,
and the row a click on a table picked.

Both pages draw only the active tab (lib.tabs.keyed_tabs), so their widgets
come and go as the reader switches tabs; these helpers keep the readers'
choices through that.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

import streamlit as st


def choice(key: str, options: Sequence[str], default: str | None = None) -> str:
    """Keep the keyed choice when it is one of `options`, and otherwise
    start it at (or put it back to) `default`, the first option unless
    given. A stored value drops out of `options` when the page offers fewer
    of them (a team that isn't in this season, a column set this season
    can't show). Call it just before drawing the widget keyed `key`.

    Set before the widget is drawn, rather than passed as its default,
    which Streamlit would warn about alongside the value the page keeps
    through session state (hold_keys).

    Returns the choice, which is what the widget shows and returns: a
    click's new value is already in session state when the rerun starts.
    A segmented control drawn after this, with required=True so a click on
    the chosen option can't clear it, is typed as possibly returning None
    all the same; callers read this value instead of narrowing that one."""
    if st.session_state.get(key) not in options:
        st.session_state[key] = options[0] if default is None else default
    return str(st.session_state[key])


def hold_keys(keys: Iterable[str]) -> None:
    """Keep the widgets keyed in `keys` as they were while their tab isn't
    drawn. The page calls this on every run, before the active tab draws.

    Only the active tab is drawn, and a widget that isn't drawn is
    forgotten twice over: Streamlit drops its value on the server at the
    end of that run, and the browser drops it when the widget leaves the
    page. Writing each value back to its key fixes the first; writing it
    on the run the widget comes back too fixes the second, since only a
    value set through session state on the widget's own run is sent to the
    browser with it. None of these widgets is given a default (see choice),
    so the write doesn't draw Streamlit's warning about one."""
    for key in keys:
        if key in st.session_state:
            st.session_state[key] = st.session_state[key]


def selected_position(table_key: str) -> int | None:
    """The position of the row picked in the st.dataframe keyed `table_key`,
    for its on_select callback, or None when the click cleared the
    selection. The click may be on the row's checkbox (a row selection) or
    on any of its cells (a cell selection, as (row, column)): a table drawn
    with both selection modes opens the row either way."""
    selection = st.session_state[table_key]["selection"]
    picked = list(selection.get("rows", [])) or [cell[0] for cell in selection.get("cells", [])]
    return int(picked[0]) if picked else None
