"""The Players page's Compare tab: two player-seasons side by side. For now
it says what it will hold."""

import streamlit as st


def render_compare() -> None:
    st.caption("Two players side by side, from any seasons, each ranked within his own season.")
