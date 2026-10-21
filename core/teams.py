"""What a team code means in a given season: franchise, era name,
conference, colour and Basketball-Reference code.

All of it comes from one CSV, dbt's team_codes seed, which
mart_team_standings joins too - so Python and the warehouse cannot drift
apart. This module reads the file itself rather than the warehouse:
ingestion runs before dbt has built anything, and the dashboard must not
depend on a warehouse table newer than the published copy.

A row is one era of one code. Lookups are by (code, season), never code
alone, so a future expansion team reusing "SEA" is not folded into
Oklahoma City. Season strings compare correctly as text ("1999-00" <
"2000-01"), and an empty bound means open-ended.
"""

from __future__ import annotations

import csv
import functools
from dataclasses import dataclass

from core import paths


@dataclass(frozen=True)
class TeamEra:
    team_code: str
    first_season: str | None  # inclusive; None = from the start of the data
    last_season: str | None  # inclusive; None = still current
    franchise_id: str
    era_name: str
    conference: str
    color: str
    bbref_code: str

    def covers(self, season: str) -> bool:
        """Whether this era includes `season`."""
        return (self.first_season is None or season >= self.first_season) and (
            self.last_season is None or season <= self.last_season
        )


@functools.cache
def eras() -> tuple[TeamEra, ...]:
    """Every row of the seed, in file order."""
    with paths.team_codes_seed_path().open(newline="", encoding="utf-8") as f:
        return tuple(
            TeamEra(
                team_code=row["team_code"],
                first_season=row["first_season"] or None,
                last_season=row["last_season"] or None,
                franchise_id=row["franchise_id"],
                era_name=row["era_name"],
                conference=row["conference"],
                color=row["color"],
                bbref_code=row["bbref_code"],
            )
            for row in csv.DictReader(f)
        )


def era(code: str, season: str) -> TeamEra:
    """The era `code` was in during `season`. KeyError when none covers it."""
    for row in eras():
        if row.team_code == code and row.covers(season):
            return row
    raise KeyError(f"no team_codes era for {code!r} in {season}")


def conference(code: str, season: str) -> str:
    """'East' or 'West'. Raises KeyError for a code/season the seed doesn't
    cover: a default here once filed the 1980s 76ers in the West for 17
    seasons without anything noticing."""
    return era(code, season).conference


def franchise_of(code: str, season: str) -> str:
    """The franchise whose contracts `code` carried in `season`. A code the
    seed doesn't cover is its own franchise - a new team starts fresh."""
    try:
        return era(code, season).franchise_id
    except KeyError:
        return code


def era_name(code: str, season: str) -> str:
    """What the team was called in `season`, e.g. "Seattle SuperSonics"."""
    try:
        return era(code, season).era_name
    except KeyError:
        return franchise_name(code)


@functools.cache
def _franchise_names() -> dict[str, str]:
    # A franchise is named after its current era under its own code: CHA is
    # "Charlotte Hornets", not the "Charlotte Bobcats" it started as.
    return {
        row.franchise_id: row.era_name
        for row in eras()
        if row.team_code == row.franchise_id and row.last_season is None
    }


def franchise_name(franchise_id: str) -> str:
    """Today's name for a franchise, or the id itself when it has none."""
    return _franchise_names().get(franchise_id, franchise_id)


@functools.cache
def _colors() -> dict[str, str]:
    return {row.team_code: row.color for row in eras()}


def color(code: str) -> str:
    """The team's identity colour, as #RRGGBB. KeyError for an unknown code."""
    return _colors()[code]


def bbref_code(code: str, season: str) -> str:
    """Basketball-Reference's code for this team-season. KeyError when the
    seed doesn't cover it."""
    return era(code, season).bbref_code
