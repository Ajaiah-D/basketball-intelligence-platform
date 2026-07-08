"""Basketball Intelligence Platform - Streamlit app entry point.

Run from the project root:
    streamlit run dashboard/app.py
"""

import sys
from pathlib import Path

import streamlit as st

# Allow `from dashboard.lib import ...` when run via `streamlit run dashboard/app.py`
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dashboard.lib import config, db, theme  # noqa: E402

st.set_page_config(
    page_title="Basketball Intelligence",
    page_icon="🏀",
    layout="wide",
    initial_sidebar_state="auto",  # desktop: open; phones: collapsed overlay
)
theme.inject(st)


@st.cache_resource(show_spinner="First boot: downloading the warehouse (one time)...")
def bootstrap_warehouse() -> None:
    """On cloud deploys the DuckDB file is not in the repo: download it
    once from WAREHOUSE_URL (e.g. a GitHub Release asset).

    cache_resource serializes concurrent sessions - on cloud boot several
    sessions start at once and racing downloads collide on the temp file."""
    url = config.warehouse_url()
    if not url or db.DB_PATH.exists():
        return
    import os

    import requests

    db.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = db.DB_PATH.with_suffix(f".download{os.getpid()}")
    try:
        with requests.get(url, stream=True, timeout=300) as r:
            r.raise_for_status()
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(chunk_size=1 << 20):
                    f.write(chunk)
        if not db.DB_PATH.exists():
            tmp.replace(db.DB_PATH)
    finally:
        tmp.unlink(missing_ok=True)


if not db.warehouse_exists():
    try:
        bootstrap_warehouse()
    except Exception as exc:
        st.error(f"Warehouse download failed: {exc}")

if not db.warehouse_exists():
    st.error("Warehouse not found. Run the pipeline first (see README):\n\n"
             "1. `python ingestion/nba_ingest.py`\n"
             "2. `python scripts/load_to_duckdb.py`\n"
             "3. `dbt run --profiles-dir .` (from dbt/basketball_intelligence)\n\n"
             "On a cloud deploy, set the `WAREHOUSE_URL` secret instead.")
    st.stop()

from dashboard.views import arcade, dev_lab, games, overview, players, teams  # noqa: E402

nav = {
    "Explore": [
        st.Page(overview.render, title="Overview", icon=":material/home:",
                default=True),  # default page serves at "/", no url_path
        st.Page(players.render, title="Players", icon=":material/person:",
                url_path="players"),
        st.Page(teams.render, title="Teams", icon=":material/groups:",
                url_path="teams"),
        st.Page(games.render, title="Games", icon=":material/sports_basketball:",
                url_path="games"),
        st.Page(arcade.render, title="Arcade", icon=":material/stadia_controller:",
                url_path="arcade"),
    ],
}
if config.dev_lab_enabled():
    nav["Developer"] = [
        st.Page(dev_lab.render, title="Dev Lab", icon=":material/terminal:",
                url_path="dev"),
    ]
pages = st.navigation(nav)

with st.sidebar:
    st.markdown(
        '<div style="padding:.2rem 0 .8rem 0"><span style="font-size:1.15rem;'
        'font-weight:800;letter-spacing:-.02em">🏀 Basketball IQ</span><br>'
        '<span style="font-size:.72rem;color:#898781">INTELLIGENCE PLATFORM</span></div>',
        unsafe_allow_html=True,
    )
    st.selectbox("Season", db.seasons(), key="season",
                 help="Applies to Overview, Players, Teams, and Games")

pages.run()
