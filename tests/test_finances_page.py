"""Headless checks that dashboard/views/finances.py renders, in every
warehouse and selection state a real deploy can be in.

Same AppTest pattern as test_predictions_page.py. The page's pieces
(viz.team_finances_trend, db.team_payroll_history) are unit-tested
elsewhere; what only a page-level test can catch is the wiring between
them - a selector that hands the query a value it can't resolve, a caption
that reads a column the dataframe doesn't have, a chart handed an empty
frame. The fixtures live in conftest.py and are shared with
test_db_metrics.py.
"""

import pytest
from streamlit.testing.v1 import AppTest

SCRIPT = """
from dashboard.views import finances
finances.render()
"""


def _run(team: str | None = None) -> AppTest:
    at = AppTest.from_string(SCRIPT)
    at.run()
    assert not at.exception, at.exception
    if team is not None:
        at.selectbox[0].select(team).run()
        assert not at.exception, at.exception
    return at


def _captions(at: AppTest) -> str:
    return " ".join(c.value for c in at.get("caption"))


def test_renders_without_a_warehouse(tmp_warehouse_without_marts):
    """A warehouse published before this feature shipped must show the
    'not loaded yet' notice, not a stack trace."""
    at = AppTest.from_string(SCRIPT)
    at.run()
    assert not at.exception
    assert len(at.get("dataframe")) == 0
    assert any("hasn't been loaded" in i.value for i in at.get("info"))


def test_renders_a_team_with_no_flagged_seasons(warehouse_with_finances_mart):
    at = _run("BOS")
    assert len(at.get("dataframe")) == 1
    captions = _captions(at)
    assert "No reliable payroll total" not in captions
    assert "unusually low" not in captions


def test_renders_a_source_gap_team_and_says_the_source_is_missing_rows(
        warehouse_with_finances_mart):
    """DEN's 1986-87 is 'sparse_source_data' - one salary row on record.
    That one really is Basketball-Reference missing the roster, so the
    strong sentence is the correct one here."""
    at = _run("DEN")
    captions = _captions(at)
    assert "No reliable payroll total exists for 1986-87" in captions
    assert "salary records for that season are missing" in captions


def test_a_real_but_cheap_roster_is_not_called_a_missing_source(
        warehouse_with_finances_mart):
    """The bug this page shipped with: MIA's 1988-89 is flagged only for
    being under half the cap, and it is a complete 13-player inaugural
    expansion roster. Telling a user Basketball-Reference's records for
    1988-89 are missing most of Miami's roster is a false published claim
    about a real NBA season, so the caption must say the number is low -
    not that the data is absent."""
    at = _run("MIA")
    captions = _captions(at)
    assert "1988-89" in captions
    assert "unusually low relative to" in captions
    assert "records for that season are missing" not in captions, (
        "the source-gap sentence must not be used for a below_half_cap season"
    )


def test_merged_franchise_renders_both_codes_as_one_history(
        warehouse_with_finances_mart):
    """Selecting GSW must show the GOS seasons too - see db.MERGED_FRANCHISES.
    The selector must also not offer the legacy code as a separate team."""
    at = AppTest.from_string(SCRIPT)
    at.run()
    assert not at.exception
    options = at.selectbox[0].options
    assert "GSW" in options and "GOS" not in options

    at.selectbox[0].select("GSW").run()
    assert not at.exception, at.exception
    table = at.get("dataframe")[0].value
    assert table["season"].tolist() == ["1995-96", "1996-97"], (
        "the pre-rename GOS season is missing from the merged franchise view"
    )
    assert "files under GOS" in _captions(at)


@pytest.mark.parametrize("team", ["BOS", "NYK", "DEN", "MIA", "GSW"])
def test_every_team_in_the_fixture_renders(warehouse_with_finances_mart, team):
    """Cheap breadth: the selector must not have an entry that crashes the
    page it belongs to."""
    _run(team)
