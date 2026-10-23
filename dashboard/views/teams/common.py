"""What the Team tab's sections share: one heading style and the grid row
height. Its own module so team.py and profile.py can both import it
without importing each other."""

import streamlit as st

from dashboard.lib import theme as T

# Every table on the Team tab is the same grid component, at the same row
# height as the Players and Advanced grids.
ROW_HEIGHT = 38


def section(title: str, help: str = "") -> None:
    """The one heading style on this tab."""
    st.markdown(f"#### {title}{T.tip(help) if help else ''}", unsafe_allow_html=True)
