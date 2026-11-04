"""What the Teams page's modules share: the tab and team-picker keys, one
heading style and the grid row height. Its own module so team.py,
profile.py and league.py can import it without importing each other or the
page."""

import streamlit as st

from dashboard.lib import theme as T

# The page's tabs (lib.tabs.keyed_tabs) and the Team tab's team picker. Both
# are keyed so a click on a Team stats row can open that team on the Team
# tab.
TEAMS_TAB_KEY = "teams_tab"
TEAM_PICK_KEY = "teams_team"

# Every table on the Teams page is the same grid component, at the same row
# height as the Players grid.
ROW_HEIGHT = 38


def section(title: str, help: str = "") -> None:
    """The one heading style on this tab."""
    st.markdown(f"#### {title}{T.tip(help) if help else ''}", unsafe_allow_html=True)
