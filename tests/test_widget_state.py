"""dashboard/lib/widget_state.py: the keyed choice, the choices held while
their tab isn't drawn, and the row a table click picked, which the Players
and Teams pages share."""

import streamlit as st
from streamlit.testing.v1 import AppTest

from dashboard.lib import widget_state as ws

# A choice on a segmented control inside a tab that only draws when it is
# active, as the pages do it: the options shrink with "few", and the tab
# comes and goes with "show".
SCRIPT = """
import streamlit as st

from dashboard.lib.widget_state import choice, hold_keys

hold_keys(["pick", "never_drawn"])
options = ["A", "B"] if st.session_state.get("few") else ["A", "B", "C"]
if st.session_state.get("show", True):
    picked = choice("pick", options)
    st.segmented_control("Pick", options, required=True, key="pick")
    st.write(f"picked={picked}")
"""


def _texts(at: AppTest) -> list[str]:
    return [m.value for m in at.markdown]


def test_choice_starts_at_the_first_option():
    at = AppTest.from_string(SCRIPT).run()
    assert not at.exception
    assert at.button_group(key="pick").value == "A"
    assert "picked=A" in _texts(at)


def test_choice_returns_what_the_reader_clicked():
    at = AppTest.from_string(SCRIPT).run()
    at.button_group(key="pick").set_value("C").run()
    assert not at.exception
    assert at.button_group(key="pick").value == "C"
    assert "picked=C" in _texts(at)


def test_a_choice_no_longer_offered_falls_back_to_the_first_option():
    at = AppTest.from_string(SCRIPT).run()
    at.button_group(key="pick").set_value("C").run()
    at.session_state["few"] = True
    at.run()
    assert not at.exception
    assert at.button_group(key="pick").value == "A"
    assert "picked=A" in _texts(at)


def test_choice_falls_back_to_a_given_default(monkeypatch):
    state: dict = {"k": "Z"}
    monkeypatch.setattr(st, "session_state", state)
    assert ws.choice("k", ["A", "B"], default="B") == "B"
    assert state["k"] == "B"
    # A value still among the options stays, default or not.
    assert ws.choice("k", ["A", "B"], default="A") == "B"


def test_hold_keys_keeps_a_choice_while_its_widget_is_not_drawn():
    at = AppTest.from_string(SCRIPT).run()
    at.button_group(key="pick").set_value("B").run()
    at.session_state["show"] = False
    at.run()
    at.run()
    assert not at.exception
    assert at.session_state["pick"] == "B"
    at.session_state["show"] = True
    at.run()
    assert at.button_group(key="pick").value == "B"
    # Sent with the widget on the run it comes back, so the browser shows it.
    assert at.button_group(key="pick").proto.set_value
    # A key that was never set is left unset.
    assert "never_drawn" not in at.session_state


def test_selected_position_reads_a_row_or_a_cell(monkeypatch):
    state: dict = {"t": {"selection": {"rows": [2], "cells": []}}}
    monkeypatch.setattr(st, "session_state", state)
    assert ws.selected_position("t") == 2
    # A click on a cell comes back as (row, column).
    state["t"] = {"selection": {"rows": [], "cells": [(4, "ppg")]}}
    assert ws.selected_position("t") == 4
    # A row selection wins when both are there.
    state["t"] = {"selection": {"rows": [1], "cells": [(4, "ppg")]}}
    assert ws.selected_position("t") == 1


def test_selected_position_is_none_when_the_click_cleared_the_selection(monkeypatch):
    monkeypatch.setattr(st, "session_state", {"t": {"selection": {"rows": [], "cells": []}}})
    assert ws.selected_position("t") is None
    # Streamlit leaves out the cells list when the table has no cell mode.
    monkeypatch.setattr(st, "session_state", {"t": {"selection": {"rows": []}}})
    assert ws.selected_position("t") is None
