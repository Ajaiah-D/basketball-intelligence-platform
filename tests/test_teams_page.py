"""The Teams page's Team tab (dashboard/views/teams/), rendered with AppTest.

Runs against the real warehouse via the `con` fixture, like
test_players_page.py, and against a copy of it without the diagnosis marts
for the fallback an older published warehouse gets.
"""

import shutil

import duckdb
import pytest
from streamlit.testing.v1 import AppTest

from core import paths
from dashboard.lib.data import core as data_core
from dashboard.lib.data import diagnosis as diagnosis_data
from dashboard.lib.data import seasons

SCRIPT = """
from dashboard.views import teams
teams.render()
"""

# The fixture warehouse's seasons: 2024-25 is modern (every rank), 1979-80
# predates the inputs (no rank at all). The full warehouse has both too.
MODERN = "2024-25"
EARLY = "1979-80"


def _app(season: str, team_name: str | None = None) -> AppTest:
    at = AppTest.from_string(SCRIPT, default_timeout=60)
    at.session_state["season"] = season
    at.run()
    assert not at.exception, at.exception
    if team_name is not None:
        at.selectbox[0].select(team_name).run()
        assert not at.exception, at.exception
    return at


def _text(at: AppTest) -> str:
    return " ".join(m.value for m in at.markdown)


def _captions(at: AppTest) -> str:
    return " ".join(c.value for c in at.caption)


def _team_names(con, season: str) -> tuple[str, str]:
    """The (best, worst) team by net rating rank that season."""
    rows = con.execute(
        """
        select s.team_name
        from main_marts.mart_team_profile p
        join main_marts.mart_team_standings s
          on s.season = p.season and s.team_id = p.team_id
        where p.season = ? and p.net_rating_rank is not null
        order by p.net_rating_rank, s.team_name
        """,
        [season],
    ).fetchall()
    assert rows, f"no ranked teams in {season}"
    return rows[0][0], rows[-1][0]


@pytest.mark.parametrize("which", [0, 1], ids=["strongest", "weakest"])
def test_team_tab_shows_the_profile(con, which):
    assert MODERN in seasons.seasons()
    team = _team_names(con, MODERN)[which]
    at = _app(MODERN, team)
    text = _text(at)
    assert "How they rank in the league" in text
    assert "Four Factors" not in text
    # Evidence, not a verdict: no "Best at / Worst at" line.
    assert "Best at" not in _captions(at)
    assert not at.info
    charts = at.get("plotly_chart")
    # The profile, the margins and the offense-vs-defense chart.
    assert len(charts) == 3


def test_an_early_season_has_no_profile_and_no_error(con):
    assert EARLY in seasons.seasons()
    at = _app(EARLY)
    assert "How they rank in the league" not in _text(at)
    assert not at.info


@pytest.fixture
def warehouse_without_profile(con, tmp_path):
    """A copy of the real warehouse as published before the diagnosis marts.
    It keeps the file name: dbt's views name the catalog, which DuckDB
    takes from the file name."""
    real = paths.warehouse_path()
    path = tmp_path / real.name
    shutil.copyfile(real, path)
    copy = duckdb.connect(str(path))
    copy.execute("drop table main_marts.mart_team_profile")
    copy.execute("drop table main_marts.mart_player_percentiles")
    copy.execute("drop table main_marts.mart_player_defense")
    copy.close()
    with data_core.use_warehouse(path):
        yield path


def test_without_the_marts_the_four_factors_show_with_one_notice(warehouse_without_profile):
    assert not diagnosis_data.profile_available()
    at = _app(MODERN)
    assert len(at.info) == 1
    assert "next data refresh" in at.info[0].value
    text = _text(at)
    assert "Four Factors" in text
    assert "How they rank in the league" not in text
