"""dashboard/lib/tabs.py: tabs whose selection lives in session state, so
another widget can open a given tab and the page renders only that one."""

from streamlit.testing.v1 import AppTest

SCRIPT = """
import streamlit as st

from dashboard.lib.tabs import keyed_tabs, open_tab

active, tabs = keyed_tabs(["A", "B", "C"], "t")
st.write(f"active={active}")
with tabs[active]:
    st.write(f"body={active}")

st.button("Open C", key="go_c", on_click=open_tab, args=("t", "C"))
# Called from the body, after the tabs are drawn: the case a table row or a
# search pick is in. Streamlit would refuse a direct write to the key here.
if st.button("Open B", key="go_b"):
    open_tab("t", "B")
    st.rerun()
"""


def _texts(at: AppTest) -> list[str]:
    return [m.value for m in at.markdown]


def test_the_first_label_is_active_by_default():
    at = AppTest.from_string(SCRIPT).run()
    assert not at.exception
    assert "active=A" in _texts(at)


def test_a_key_set_before_the_tabs_render_selects_that_tab():
    at = AppTest.from_string(SCRIPT)
    at.session_state["t"] = "B"
    at.run()
    assert not at.exception
    assert "active=B" in _texts(at)
    assert "body=B" in _texts(at)


def test_an_unknown_label_in_the_key_falls_back_to_the_first_tab():
    at = AppTest.from_string(SCRIPT)
    at.session_state["t"] = "Z"
    at.run()
    assert not at.exception
    assert "active=A" in _texts(at)


def test_open_tab_from_a_button_callback_opens_that_tab():
    at = AppTest.from_string(SCRIPT).run()
    assert "active=A" in _texts(at)
    at.button("go_c").click().run()
    assert not at.exception
    assert "active=C" in _texts(at)
    assert "body=C" in _texts(at)


def test_open_tab_from_the_page_body_after_the_tabs_are_drawn():
    at = AppTest.from_string(SCRIPT).run()
    at.button("go_b").click().run()
    assert not at.exception
    assert "active=B" in _texts(at)


def test_the_selection_survives_an_unrelated_rerun():
    at = AppTest.from_string(SCRIPT).run()
    at.button("go_c").click().run()
    at.run()
    assert "active=C" in _texts(at)
