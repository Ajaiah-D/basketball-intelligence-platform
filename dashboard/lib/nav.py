"""Moving between pages from inside one.

app.py builds every st.Page and registers it here by name, so a view can
switch to another page (nav.go("players")) without importing app.py, which
is the script Streamlit runs and not a module to import.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

_PAGES: dict[str, Any] = {}


def register(name: str, page: Any) -> None:
    """Make `page` (an st.Page) reachable as nav.go(name)."""
    _PAGES[name] = page


def go(name: str) -> None:
    """Switch to the page registered as `name`. Raises KeyError for a name
    app.py never registered (a view rendered on its own, as in a test)."""
    if name not in _PAGES:
        raise KeyError(f"no page registered as {name!r}; app.py registers them")
    st.switch_page(_PAGES[name])
