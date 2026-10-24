"""Basketball Intelligence Platform - Streamlit app entry point.

Run from the project root:
    streamlit run dashboard/app.py
"""

import sys
from pathlib import Path

import streamlit as st

# Allow `from dashboard.lib import ...` when run via `streamlit run dashboard/app.py`
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import paths
from dashboard.lib import config, nav, theme
from dashboard.lib.data import core as data_core
from dashboard.lib.data import seasons
from dashboard.lib.state import SEASON_KEY

st.set_page_config(
    page_title="Basketball Intelligence",
    page_icon="🏀",
    layout="wide",
    initial_sidebar_state="auto",  # desktop: open; phones: collapsed overlay
)
theme.inject(st)


def _remote_version(url: str) -> str | None:
    import requests

    version_url = url.rsplit("/", 1)[0] + "/version.txt"
    try:
        r = requests.get(version_url, timeout=10)
        r.raise_for_status()
        return r.text.strip()
    except Exception:
        return None


@st.cache_resource(ttl=3600, show_spinner="Downloading the warehouse...")
def bootstrap_warehouse() -> None:
    """On cloud deploys the DuckDB file is not in the repo: download it from
    WAREHOUSE_URL (e.g. a GitHub Release asset). Re-checked hourly (cache
    ttl) against a small version.txt sitting next to the asset, so a fresh
    weekly data refresh reaches the live app without a manual reboot. That
    refresh is scripts/weekly_refresh.py, run by the local Windows Scheduled
    Task BasketballIntelligence-WeeklyRefresh, which publishes the warehouse
    to the data-v1 GitHub release (see DEPLOYMENT.md and docs/adr/0004).

    cache_resource serializes concurrent sessions - on cloud boot several
    sessions start at once and racing downloads collide on the temp file."""
    url = config.warehouse_url()
    if not url:
        return

    # The data layer decides where the warehouse is, so the download lands
    # in the file every page reads.
    warehouse = data_core.warehouse_path()
    version_path = paths.warehouse_version_path(warehouse)
    remote_version = _remote_version(url)
    local_version = version_path.read_text().strip() if version_path.exists() else None
    if warehouse.exists() and (remote_version is None or remote_version == local_version):
        return

    import os

    import requests

    warehouse.parent.mkdir(parents=True, exist_ok=True)
    tmp = warehouse.with_suffix(f".download{os.getpid()}")
    try:
        with requests.get(url, stream=True, timeout=300) as r:
            r.raise_for_status()
            with tmp.open("wb") as f:
                for chunk in r.iter_content(chunk_size=1 << 20):
                    f.write(chunk)
        tmp.replace(warehouse)
        # Drop cached results from the old file. The data layer keys its
        # cache on the file's mtime as well, so this is belt and braces.
        data_core.clear_caches()
        if remote_version:
            version_path.write_text(remote_version)
    finally:
        tmp.unlink(missing_ok=True)


try:
    bootstrap_warehouse()
except Exception as exc:
    st.error(f"Warehouse download failed: {exc}")

if not data_core.warehouse_exists():
    st.error(
        "Warehouse not found. Run the pipeline first (see README):\n\n"
        "1. `python ingestion/nba_ingest.py`\n"
        "2. `python scripts/load_to_duckdb.py`\n"
        "3. `dbt build --profiles-dir .` (from dbt/basketball_intelligence)\n\n"
        "On a cloud deploy, set the `WAREHOUSE_URL` secret instead."
    )
    st.stop()

from dashboard.views import (
    advanced,
    arcade,
    dev_lab,
    finances,
    games,
    overview,
    players,
    predictions,
    teams,
)

# Every page by name, so views can switch to one through lib/nav.py.
explore = {
    # The default page serves at "/", with no url_path.
    "overview": st.Page(overview.render, title="Overview", icon=":material/home:", default=True),
    "players": st.Page(
        players.render, title="Players", icon=":material/person:", url_path="players"
    ),
    "teams": st.Page(teams.render, title="Teams", icon=":material/groups:", url_path="teams"),
    "games": st.Page(
        games.render, title="Games", icon=":material/sports_basketball:", url_path="games"
    ),
    "advanced": st.Page(
        advanced.render, title="Advanced", icon=":material/insights:", url_path="advanced"
    ),
    "arcade": st.Page(
        arcade.render, title="Arcade", icon=":material/stadia_controller:", url_path="arcade"
    ),
    "predictions": st.Page(
        predictions.render,
        title="Predictions",
        icon=":material/query_stats:",
        url_path="predictions",
    ),
    "finances": st.Page(
        finances.render, title="Finances", icon=":material/payments:", url_path="finances"
    ),
}
for name, page in explore.items():
    nav.register(name, page)
sections = {"Explore": list(explore.values())}
if config.dev_lab_enabled():
    sections["Developer"] = [
        st.Page(dev_lab.render, title="Dev Lab", icon=":material/terminal:", url_path="dev"),
    ]
pages = st.navigation(sections)

with st.sidebar:
    st.markdown(
        '<div style="padding:.2rem 0 .8rem 0"><span style="font-size:1.15rem;'
        'font-weight:800;letter-spacing:-.02em">🏀 Basketball IQ</span><br>'
        f'<span style="font-size:.72rem;color:{theme.MUTED}">INTELLIGENCE PLATFORM</span></div>',
        unsafe_allow_html=True,
    )
    st.selectbox(
        "Season",
        seasons.seasons(),
        key=SEASON_KEY,
        help="Applies to Overview, Players, Teams, and Games",
    )

pages.run()
