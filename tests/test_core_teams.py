"""core.teams: the team_codes seed is the one place for what a team code
means in a given season - franchise, era name, conference, colour and
Basketball-Reference code. dbt joins the same CSV, so these tests also pin
the Python reading of it to the mart's."""

import itertools
import re

import pytest

from core import paths, teams


@pytest.mark.parametrize(
    "code,season,franchise,name",
    [
        ("SEA", "2007-08", "OKC", "Seattle SuperSonics"),
        ("OKC", "2008-09", "OKC", "Oklahoma City Thunder"),
        ("VAN", "2000-01", "MEM", "Vancouver Grizzlies"),
        ("NJN", "2011-12", "BKN", "New Jersey Nets"),
        ("KCK", "1984-85", "SAC", "Kansas City Kings"),
        # The original Hornets' contracts moved to New Orleans in 2002.
        ("CHH", "2001-02", "NOP", "Charlotte Hornets"),
        ("NOH", "2012-13", "NOP", "New Orleans Hornets"),
        ("NOK", "2005-06", "NOP", "New Orleans/Oklahoma City Hornets"),
        ("NOP", "2013-14", "NOP", "New Orleans Pelicans"),
        # Today's Hornets start as the 2004 Bobcats.
        ("CHA", "2004-05", "CHA", "Charlotte Bobcats"),
        ("CHA", "2013-14", "CHA", "Charlotte Bobcats"),
        ("CHA", "2014-15", "CHA", "Charlotte Hornets"),
        ("WAS", "1996-97", "WAS", "Washington Bullets"),
        ("WAS", "1997-98", "WAS", "Washington Wizards"),
        ("GOS", "1995-96", "GSW", "Golden State Warriors"),
        ("PHL", "1995-96", "PHI", "Philadelphia 76ers"),
        ("SAN", "1995-96", "SAS", "San Antonio Spurs"),
        ("UTH", "1995-96", "UTA", "Utah Jazz"),
        ("LAC", "1984-85", "LAC", "LA Clippers"),
        ("BOS", "2023-24", "BOS", "Boston Celtics"),
    ],
)
def test_franchise_and_era_name(code, season, franchise, name):
    assert teams.franchise_of(code, season) == franchise
    assert teams.era_name(code, season) == name


def test_a_future_seattle_team_is_not_folded_into_oklahoma_city():
    """An expansion team reusing SEA starts fresh: new contracts, no payroll
    history. Only the 1979-2008 SuperSonics belong to OKC's money history."""
    assert teams.franchise_of("SEA", "2028-29") == "SEA"
    assert teams.era_name("SEA", "2028-29") == "SEA"
    assert teams.franchise_name("SEA") == "SEA"


def test_thirty_franchises_each_named_by_its_current_era():
    franchise_ids = {era.franchise_id for era in teams.eras()}
    assert len(franchise_ids) == 30
    assert teams.franchise_name("CHA") == "Charlotte Hornets"
    assert teams.franchise_name("WAS") == "Washington Wizards"
    unnamed = {f for f in franchise_ids if teams.franchise_name(f) == f}
    assert not unnamed


@pytest.mark.parametrize(
    "code,season,expected",
    [
        ("PHL", "1985-86", "East"),  # once misfiled West by a default
        ("GOS", "1985-86", "West"),
        ("SAN", "1985-86", "West"),
        ("CHH", "1995-96", "East"),
        ("NOH", "2010-11", "West"),
        ("SEA", "1999-00", "West"),
        ("WAS", "1990-91", "East"),
        ("WAS", "2020-21", "East"),
        ("TOR", "2025-26", "East"),
    ],
)
def test_conference(code, season, expected):
    assert teams.conference(code, season) == expected


@pytest.mark.parametrize("code,season", [("XXX", "2020-21"), ("SEA", "2028-29")])
def test_conference_never_defaults(code, season):
    """No era covers these, so there is no answer - not a guess at West."""
    with pytest.raises(KeyError):
        teams.conference(code, season)


def test_colour_is_per_code_and_unknown_codes_raise():
    assert teams.color("BOS") == "#00B25A"
    assert teams.color("SEA") == "#2DA05A"
    assert teams.color("CAP") == "#E31837"
    with pytest.raises(KeyError):
        teams.color("XXX")


@pytest.mark.parametrize(
    "code,season,expected",
    [
        ("SAN", "1990-91", "SAS"),
        ("PHX", "1984-85", "PHO"),
        ("BKN", "2012-13", "BRK"),
        ("WAS", "1996-97", "WSB"),
        ("WAS", "1997-98", "WAS"),
        ("CHA", "2013-14", "CHA"),
        ("CHA", "2014-15", "CHO"),
        ("SEA", "2000-01", "SEA"),
    ],
)
def test_bbref_code(code, season, expected):
    assert teams.bbref_code(code, season) == expected


def test_bbref_code_raises_for_an_unknown_code():
    with pytest.raises(KeyError):
        teams.bbref_code("XXX", "2020-21")


# --- The seed itself -----------------------------------------------------------


def test_seed_lives_with_the_dbt_project():
    assert paths.team_codes_seed_path() == (
        paths.PROJECT_ROOT / "dbt" / "basketball_intelligence" / "seeds" / "team_codes.csv"
    )
    assert paths.team_codes_seed_path().exists()


def test_seed_rows_are_well_formed():
    season = re.compile(r"^\d{4}-\d{2}$")
    for era in teams.eras():
        for bound in (era.first_season, era.last_season):
            assert bound is None or season.match(bound), era
        assert era.conference in ("East", "West"), era
        assert re.match(r"^#[0-9A-F]{6}$", era.color), era
        assert era.franchise_id and era.era_name and era.bbref_code, era


def test_eras_of_one_code_never_overlap_and_share_one_colour():
    by_code: dict[str, list[teams.TeamEra]] = {}
    for era in teams.eras():
        by_code.setdefault(era.team_code, []).append(era)
    for code, rows in by_code.items():
        assert len({r.color for r in rows}) == 1, code
        rows.sort(key=lambda r: r.first_season or "")
        for earlier, later in itertools.pairwise(rows):
            assert earlier.last_season is not None, code
            assert later.first_season is not None, code
            assert earlier.last_season < later.first_season, code


# --- Against the warehouse -------------------------------------------------------


def test_python_and_the_standings_mart_agree_on_every_conference(con):
    """dbt joins the same seed on code and season range; every team-season in
    the standings must come out the same here."""
    rows = con.execute(
        "select season, team_abbreviation, conference from main_marts.mart_team_standings"
    ).fetchall()
    assert rows
    differ = [(s, c, conf) for s, c, conf in rows if teams.conference(c, s) != conf]
    assert not differ, differ[:10]


def test_every_code_in_the_data_has_an_era(con):
    rows = con.execute(
        """
        select distinct season, team_abbreviation from main_staging.stg_team_game_logs
        union
        select distinct season, team_abbreviation from main_staging.stg_team_payroll
        """
    ).fetchall()
    uncovered = []
    for season, code in rows:
        try:
            teams.era(code, season)
        except KeyError:
            uncovered.append((season, code))
    assert not uncovered, sorted(uncovered)[:10]
