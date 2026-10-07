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


def _run(team: str | None = None, season: str | None = None) -> AppTest:
    """The season comes from the sidebar (session_state["season"]), as on
    every page; the page's one selectbox is the team (a franchise key; the
    widget shows full names via format_func)."""
    at = AppTest.from_string(SCRIPT)
    if season is not None:
        at.session_state["season"] = season
    at.run()
    assert not at.exception, at.exception
    if team is not None:
        at.selectbox[0].select(team).run()
        assert not at.exception, at.exception
    return at


def _markdown(at: AppTest) -> str:
    # Dollar signs reach st.markdown escaped (finances._prose); compare
    # against the text a reader actually sees.
    return " ".join(m.value for m in at.markdown).replace("\\$", "$")


def test_dollar_signs_are_escaped_so_markdown_does_not_render_math(
        warehouse_with_finances_mart):
    raw = " ".join(m.value for m in _run("BOS").markdown)
    assert "\\$180.0M" in raw
    assert "spent $" not in raw


def test_renders_a_team_with_no_flagged_seasons(warehouse_with_finances_mart):
    at = _run("BOS")
    assert len(at.get("dataframe")) == 1
    captions = _captions(at)
    assert "No reliable payroll total" not in captions
    assert "unusually low" not in captions


def test_says_when_the_salary_data_was_updated(warehouse_with_finances_mart):
    at = _run()
    assert "Salary data updated Sep 23, 2026 · covers through 2023-24." in _captions(at)


def test_team_summary_explains_the_number_and_its_cause(warehouse_with_finances_mart):
    at = _run("BOS")
    text = _markdown(at)
    assert "In 2023-24 the Boston Celtics spent $180.0M, the highest payroll of 2 teams." in text
    assert "$7.7M over the first apron and $2.8M under the second apron" in text
    assert "(Player One, Player Two and Player Three) made up 50% of the payroll" in text
    assert "Biggest contracts" in text


def test_league_summary_and_explainer_render(warehouse_with_finances_mart):
    at = _run()
    text = _markdown(at)
    assert "In 2023-24, 2 of 2 teams were over the salary cap" in text
    assert "soft" in text  # the how-to-read explainer


def test_old_warehouse_without_contracts_or_dates_still_renders(legacy_finances_warehouse):
    at = _run("BOS")
    assert "update date not recorded" in _captions(at)
    assert "Biggest contracts" not in _markdown(at)
    assert "the highest payroll of 2 teams" in _markdown(at)


def test_a_team_with_no_row_that_season_says_so(warehouse_with_finances_mart):
    at = _run("DEN")  # the fixture's DEN has 1986-87 and 1995-96 only
    assert any("No payroll data for the Denver Nuggets in 2023-24" in i.value
               for i in at.get("info"))


def test_renders_a_source_gap_team_and_says_the_source_is_missing_rows(
        warehouse_with_finances_mart):
    """DEN's 1986-87 is 'sparse_source_data' - one salary row on record.
    That one really is Basketball-Reference missing the roster, so the
    strong sentence is the correct one here."""
    at = _run("DEN", season="1986-87")
    captions = _captions(at)
    assert "No reliable payroll total exists for 1986-87" in captions
    assert "salary records for that season are missing" in captions
    assert "There's no reliable payroll figure for the Denver Nuggets in 1986-87." \
        in _markdown(at)


def test_a_real_but_cheap_roster_is_not_called_a_missing_source(
        warehouse_with_finances_mart):
    """MIA's 1988-89 is flagged only for being under half the cap, and it is
    a complete 13-player inaugural expansion roster. The caption must say the
    number is low - not that the data is absent."""
    at = _run("MIA")
    captions = _captions(at)
    assert "1988-89" in captions
    assert "unusually low relative to" in captions
    assert "records for that season are missing" not in captions


def test_merged_franchise_renders_both_codes_as_one_history(warehouse_with_finances_mart):
    """GSW must include the GOS seasons, and the selector lists full names,
    never a legacy code."""
    at = _run()
    options = at.selectbox[0].options
    assert "Golden State Warriors" in options
    assert "GOS" not in options and "GSW" not in options
    at.selectbox[0].select("GSW").run()
    assert not at.exception, at.exception
    table = at.get("dataframe")[0].value
    assert table["Season"].tolist() == ["1995-96", "1996-97"]


@pytest.mark.parametrize("team", ["BOS", "NYK", "DEN", "MIA", "GSW"])
def test_every_team_in_the_fixture_renders(warehouse_with_finances_mart, team):
    _run(team)


def test_a_sidebar_season_before_payroll_data_falls_back_to_the_latest(
        warehouse_with_finances_mart):
    at = _run(season="1980-81")
    assert "No salary data for 1980-81 (it starts in 1986-87), so this shows 2023-24."         in _captions(at)
    assert "In 2023-24, 2 of 2 teams were over the salary cap" in _markdown(at)


def test_a_season_with_too_few_reliable_payrolls_skips_the_comparison(
        warehouse_with_finances_mart):
    """1986-87's source is missing most rosters (1 of 23 teams usable in the
    real data); a 'league snapshot' of one bar compares nothing."""
    at = _run("DEN", season="1986-87")
    assert any("Too few teams have reliable salary data in 1986-87" in i.value
               for i in at.get("info"))
