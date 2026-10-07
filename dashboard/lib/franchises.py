"""Which franchise a team code belongs to, season by season, and what the
team was called then - for the Finances page.

Payroll history follows the contracts. A relocation is the same legal
business moving its contracts, players and staff to a new city, so its
payroll stays one continuous line: the 2008 Thunder carried the SuperSonics'
books, and the 2002 New Orleans Hornets carried Charlotte's. The NBA has
since handed Charlotte its 1988-2002 records and name back (2014), and would
very likely do the same for Seattle if it gets a team again - but that is
about records, not money. FRANCHISE_NOTES says so on the page.

Mapping is by (code, season), never code alone, so a future expansion team
that reuses "SEA" is its own franchise rather than being folded into
Oklahoma City.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

FRANCHISE_NAMES = {
    "ATL": "Atlanta Hawks", "BOS": "Boston Celtics", "BKN": "Brooklyn Nets",
    "CHA": "Charlotte Hornets", "CHI": "Chicago Bulls", "CLE": "Cleveland Cavaliers",
    "DAL": "Dallas Mavericks", "DEN": "Denver Nuggets", "DET": "Detroit Pistons",
    "GSW": "Golden State Warriors", "HOU": "Houston Rockets", "IND": "Indiana Pacers",
    "LAC": "LA Clippers", "LAL": "Los Angeles Lakers", "MEM": "Memphis Grizzlies",
    "MIA": "Miami Heat", "MIL": "Milwaukee Bucks", "MIN": "Minnesota Timberwolves",
    "NOP": "New Orleans Pelicans", "NYK": "New York Knicks",
    "OKC": "Oklahoma City Thunder", "ORL": "Orlando Magic",
    "PHI": "Philadelphia 76ers", "PHX": "Phoenix Suns",
    "POR": "Portland Trail Blazers", "SAC": "Sacramento Kings",
    "SAS": "San Antonio Spurs", "TOR": "Toronto Raptors", "UTA": "Utah Jazz",
    "WAS": "Washington Wizards",
}


@dataclass(frozen=True)
class Era:
    code: str
    franchise: str
    name: str
    last_season: str | None = None  # inclusive; None = every season under this code


# Codes whose franchise or name differs from the default (a code is its own
# franchise, named FRANCHISE_NAMES[code]). Checked in order, first match wins.
# Season strings compare correctly as text ("1999-00" < "2000-01").
ERAS = [
    Era("SEA", "OKC", "Seattle SuperSonics", last_season="2007-08"),
    Era("VAN", "MEM", "Vancouver Grizzlies"),
    Era("NJN", "BKN", "New Jersey Nets"),
    Era("KCK", "SAC", "Kansas City Kings"),
    Era("CHH", "NOP", "Charlotte Hornets", last_season="2001-02"),
    Era("NOH", "NOP", "New Orleans Hornets"),
    Era("NOK", "NOP", "New Orleans/Oklahoma City Hornets"),
    Era("CHA", "CHA", "Charlotte Bobcats", last_season="2013-14"),
    Era("WAS", "WAS", "Washington Bullets", last_season="1996-97"),
    # nba_api's own 1996-97 code renames - same team, same name.
    Era("GOS", "GSW", "Golden State Warriors"),
    Era("PHL", "PHI", "Philadelphia 76ers"),
    Era("SAN", "SAS", "San Antonio Spurs"),
    Era("UTH", "UTA", "Utah Jazz"),
]

FRANCHISE_NOTES = {
    "OKC": ("Includes the Seattle SuperSonics years in this data (1984-85 to "
            "2007-08). Seattle kept the SuperSonics name and history, but the "
            "team's contracts and roster moved to Oklahoma City in 2008, so that "
            "payroll is shown here."),
    "NOP": ("Includes the original Charlotte Hornets (1988-89 to 2001-02). The "
            "NBA credits those seasons' records to today's Charlotte Hornets, but "
            "the contracts and roster moved to New Orleans in 2002, so that "
            "payroll is shown here."),
    "CHA": ("Starts with the Charlotte Bobcats in 2004-05. The NBA credits the "
            "1988-2002 Hornets' records to Charlotte, but those contracts moved "
            "to New Orleans in 2002, so that payroll is shown under the New "
            "Orleans Pelicans."),
}


def _era(code: str, season: str) -> Era | None:
    for era in ERAS:
        if era.code == code and (era.last_season is None or season <= era.last_season):
            return era
    return None


def franchise_of(code: str, season: str) -> str:
    era = _era(code, season)
    return era.franchise if era else code


def era_name(code: str, season: str) -> str:
    era = _era(code, season)
    return era.name if era else FRANCHISE_NAMES.get(code, code)


def franchise_name(franchise: str) -> str:
    return FRANCHISE_NAMES.get(franchise, franchise)


def annotate(df: pd.DataFrame) -> pd.DataFrame:
    """A copy of df (needs team_abbreviation and season) with franchise and
    era_name columns added."""
    out = df.copy()
    pairs = list(zip(out["team_abbreviation"], out["season"]))
    out["franchise"] = [franchise_of(c, s) for c, s in pairs]
    out["era_name"] = [era_name(c, s) for c, s in pairs]
    return out


def era_spans(team_df: pd.DataFrame) -> list[tuple[str, str, str]]:
    """(first_season, last_season, era_name) for each consecutive run of one
    name in an annotated, single-franchise frame, oldest first."""
    spans: list[tuple[str, str, str]] = []
    ordered = team_df.sort_values("season")[["season", "era_name"]]
    for season, name in ordered.itertuples(index=False):
        if spans and spans[-1][2] == name:
            spans[-1] = (spans[-1][0], season, name)
        else:
            spans.append((season, season, name))
    return spans
