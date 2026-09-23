"""Tests for the shared season/team-code lookup both payroll entry points use."""

import pytest

from scripts import season_teams


@pytest.fixture(scope="module")
def by_season(con):  # `con` only to reuse conftest's skip-if-no-warehouse guard
    return season_teams.seasons_and_teams()


def test_seasons_and_teams_starts_at_the_first_capped_season(by_season):
    assert min(by_season) == season_teams.FIRST_PAYROLL_SEASON


def test_seasons_and_teams_returns_lowercase_team_codes_not_a_keyerror(by_season):
    # Regression guard for the "as team_abbreviation" alias in the query. The
    # stored nba_api column is TEAM_ABBREVIATION; DuckDB matches it
    # case-insensitively but names the result column after the stored casing,
    # so dropping the alias as a "no-op self-alias" makes the pandas lookup
    # inside seasons_and_teams() raise KeyError against the real warehouse.
    #
    # 1984-85 (not e.g. 2009-10) because it's guaranteed present in every
    # environment - CI builds a reduced warehouse from committed fixtures
    # covering only 1984-85 and 2024-25 for the payroll era, not full history.
    teams = by_season["1984-85"]
    assert teams, "1984-85 should have team codes"
    assert all(t.isupper() and len(t) == 3 for t in teams)


def test_seasons_and_teams_tracks_real_expansion_history(by_season):
    # Franchise counts are facts about the league, not about this repo's data
    # volume, so they don't shift on a refresh. 1984-85 and 2024-25 are
    # guaranteed present in every environment (CI's reduced fixture set
    # covers exactly those two payroll-era seasons - see
    # .github/workflows/tests.yml); the others only exist against a full
    # local warehouse and are checked opportunistically, not required.
    assert len(by_season["1984-85"]) == 23
    assert len(by_season["2024-25"]) == 30
    if "1986-87" in by_season:
        assert len(by_season["1986-87"]) == 23
    if "1989-90" in by_season:
        assert len(by_season["1989-90"]) == 27


def test_seasons_are_ordered_oldest_first(by_season):
    assert list(by_season) == sorted(by_season)


def test_current_season_and_teams_is_the_newest_season(by_season):
    season, teams = season_teams.current_season_and_teams()
    assert season == max(by_season)
    assert teams == by_season[season]
    assert teams == sorted(teams)
