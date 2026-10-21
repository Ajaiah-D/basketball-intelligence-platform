"""Which franchise a team code belongs to, season by season, and what the
team was called then - for the Finances page.

Payroll history follows the contracts. A relocation is the same legal
business moving its contracts, players and staff to a new city, so its
payroll stays one continuous line: the 2008 Thunder carried the SuperSonics'
books, and the 2002 New Orleans Hornets carried Charlotte's. The NBA has
since handed Charlotte its 1988-2002 records and name back (2014), and would
very likely do the same for Seattle if it gets a team again - but that is
about records, not money. FRANCHISE_NOTES says so on the page.

The (code, season) -> franchise and era-name mapping is dbt's team_codes
seed, read through core.teams. It is by (code, season), never code alone,
so a future expansion team that reuses "SEA" is its own franchise rather
than being folded into Oklahoma City.
"""

from __future__ import annotations

import pandas as pd

from core import teams

FRANCHISE_NOTES = {
    "OKC": (
        "Includes the Seattle SuperSonics years in this data (1984-85 to "
        "2007-08). Seattle kept the SuperSonics name and history, but the "
        "team's contracts and roster moved to Oklahoma City in 2008, so that "
        "payroll is shown here."
    ),
    "NOP": (
        "Includes the original Charlotte Hornets (1988-89 to 2001-02). The "
        "NBA credits those seasons' records to today's Charlotte Hornets, but "
        "the contracts and roster moved to New Orleans in 2002, so that "
        "payroll is shown here."
    ),
    "CHA": (
        "Starts with the Charlotte Bobcats in 2004-05. The NBA credits the "
        "1988-2002 Hornets' records to Charlotte, but those contracts moved "
        "to New Orleans in 2002, so that payroll is shown under the New "
        "Orleans Pelicans."
    ),
}


def annotate(df: pd.DataFrame) -> pd.DataFrame:
    """A copy of df (needs team_abbreviation and season) with franchise and
    era_name columns added."""
    out = df.copy()
    pairs = list(zip(out["team_abbreviation"], out["season"], strict=True))
    out["franchise"] = [teams.franchise_of(c, s) for c, s in pairs]
    out["era_name"] = [teams.era_name(c, s) for c, s in pairs]
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
