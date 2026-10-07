"""Franchise lineage for the Finances page: payroll follows the contracts,
and the mapping is by (code, season), never by code alone."""

import pandas as pd
import pytest

from dashboard.lib import franchises


@pytest.mark.parametrize("code,season,franchise,name", [
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
    ("BOS", "2023-24", "BOS", "Boston Celtics"),
])
def test_franchise_and_era_name(code, season, franchise, name):
    assert franchises.franchise_of(code, season) == franchise
    assert franchises.era_name(code, season) == name


def test_a_future_seattle_team_is_not_folded_into_oklahoma_city():
    """An expansion team reusing SEA starts fresh: new contracts, no payroll
    history. Only the 1984-2008 SuperSonics belong to OKC's money history."""
    assert franchises.franchise_of("SEA", "2028-29") == "SEA"
    assert franchises.franchise_name("SEA") == "SEA"


def test_every_franchise_key_in_use_has_a_full_name():
    keys = {era.franchise for era in franchises.ERAS}
    assert keys <= set(franchises.FRANCHISE_NAMES)
    assert len(franchises.FRANCHISE_NAMES) == 30


def test_annotate_and_era_spans():
    df = pd.DataFrame({
        "season": ["2006-07", "2007-08", "2008-09", "2009-10"],
        "team_abbreviation": ["SEA", "SEA", "OKC", "OKC"],
    })
    out = franchises.annotate(df)
    assert out["franchise"].tolist() == ["OKC"] * 4
    assert franchises.era_spans(out) == [
        ("2006-07", "2007-08", "Seattle SuperSonics"),
        ("2008-09", "2009-10", "Oklahoma City Thunder"),
    ]
    assert "franchise" not in df.columns, "annotate must not mutate its input"


def test_every_code_in_the_real_mart_maps_to_a_named_franchise(con):
    rows = con.execute(
        "select distinct team_abbreviation, season from main_marts.mart_team_finances"
    ).fetchall()
    unnamed = {(c, s) for c, s in rows
               if franchises.franchise_of(c, s) not in franchises.FRANCHISE_NAMES}
    assert not unnamed, f"codes with no franchise name: {sorted(unnamed)[:10]}"
