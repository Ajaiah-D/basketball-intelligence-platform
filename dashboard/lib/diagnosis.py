"""The rules behind the Teams page's diagnosis views: which stats make up a
team's league-ranks profile, and the ten areas of the player breakdown,
each with the player measures that sit under its team stat.

Pure: no Streamlit and no SQL. The numbers come from
dashboard/lib/data/diagnosis.py (mart_team_profile for the team,
team_drivers() for the rotation).

The views show evidence and leave the verdict to the reader, so nothing
here words a judgement: the areas only name their measures, say how each
one prints, and carry a caption on method and limits.
"""

from __future__ import annotations

from typing import Any, NamedTuple

import pandas as pd


class ProfileStat(NamedTuple):
    """One bar of the profile chart: a mart_team_profile column (its rank
    and percentile are `<key>_rank` and `<key>_pctile`)."""

    key: str
    label: str
    group: str  # "Offense" | "Defense" | "Style"
    term: str  # the glossary.TERMS entry for its hover
    # False for volume and style stats (pace, 3-pt rate): more of them is a
    # choice, not better or worse, so the chart draws them in gray with a
    # rank that names what it counts.
    judged: bool = True


# The spec's order. Pace and 3-pt rate are shown but never judged.
PROFILE_STATS: list[ProfileStat] = [
    ProfileStat("offensive_rating", "Offensive rating", "Offense", "Offensive rating"),
    ProfileStat("effective_fg_pct", "eFG%", "Offense", "eFG%"),
    ProfileStat("three_pt_pct", "3P%", "Offense", "3P%"),
    ProfileStat("three_pt_rate", "3-pt rate", "Offense", "3-pt rate", judged=False),
    ProfileStat("turnover_pct", "Turnover rate", "Offense", "Turnover rate"),
    ProfileStat("offensive_rebound_pct", "Off. rebound %", "Offense", "Off. rebound %"),
    ProfileStat("free_throw_rate", "FT rate", "Offense", "FT rate"),
    ProfileStat("assist_pct", "Assist rate", "Offense", "Assist rate"),
    ProfileStat("defensive_rating", "Defensive rating", "Defense", "Defensive rating"),
    ProfileStat("opp_effective_fg_pct", "Opp eFG%", "Defense", "Opp eFG%"),
    ProfileStat("opp_three_pt_pct", "Opp 3P%", "Defense", "Opp 3P%"),
    ProfileStat("opp_turnover_pct", "Opp turnover rate", "Defense", "Opp turnover rate"),
    ProfileStat("defensive_rebound_pct", "Def. rebound %", "Defense", "Def. rebound %"),
    ProfileStat("opp_free_throw_rate", "Opp FT rate", "Defense", "Opp FT rate"),
    ProfileStat("pace", "Pace", "Style", "Pace", judged=False),
]

PROFILE_BY_KEY: dict[str, ProfileStat] = {s.key: s for s in PROFILE_STATS}


def missing(value: Any) -> bool:
    """None, NaN or pd.NA."""
    return value is None or bool(pd.isna(value))


class Measure(NamedTuple):
    """One player measure of an area: a team_drivers() column, its short
    label, its glossary.TERMS entry and how it prints."""

    col: str
    label: str
    term: str
    # "pct" (a 0-100 rate: 57.5%), "share" (a 0-1 share, printed as a
    # percentage), "ratio" (.236), "num" (3.1) or "signed" (+3.2 / -5.6).
    kind: str

    def format(self, value: Any) -> str:
        """The value as the chart and table print it; "-" when missing."""
        if missing(value):
            return "-"
        v = float(value)
        if self.kind == "pct":
            return f"{v:.1f}%"
        if self.kind == "share":
            return f"{100 * v:.1f}%"
        if self.kind == "ratio":
            return f"{v:.3f}".removeprefix("0")
        if self.kind == "signed":
            return f"{v:+.1f}"
        return f"{v:.1f}"


class Area(NamedTuple):
    """One area of the player breakdown: the team stat it sits under and
    the player measures (team_drivers() columns) shown for it."""

    key: str
    label: str
    team_stat: str  # a PROFILE_STATS key
    team_rank_col: str
    measures: list[Measure]
    defensive: bool
    caption: str  # method and limits, one sentence


_USG = Measure("usage_pct", "USG%", "USG%", "pct")

# Box scores record far less of defense than of offense; every defensive
# area's caption says so.
_FILM = "box scores record far less of defense than of offense, and none of it replaces film."

AREAS: list[Area] = [
    Area(
        "scoring",
        "Scoring efficiency",
        "effective_fg_pct",
        "effective_fg_pct_rank",
        [Measure("true_shooting_pct", "TS%", "TS%", "pct"), _USG],
        False,
        "TS% and usage cover each player's whole season, so a traded player's "
        "include his other team.",
    ),
    Area(
        "three_point",
        "3-point shooting",
        "three_pt_pct",
        "three_pt_pct_rank",
        [
            Measure("three_pa_per_game", "3PA per game", "3PA", "num"),
            Measure("fg3_pct", "3P%", "3P%", "pct"),
        ],
        False,
        "Three-point attempts per game and 3P% count only each player's games for this team.",
    ),
    Area(
        "ball_security",
        "Ball security",
        "turnover_pct",
        "turnover_pct_rank",
        [Measure("turnover_pct", "TOV%", "TOV%", "pct"), _USG],
        False,
        "Turnover rate and usage cover each player's whole season, so a traded "
        "player's include his other team.",
    ),
    Area(
        "offensive_rebounding",
        "Offensive rebounding",
        "offensive_rebound_pct",
        "offensive_rebound_pct_rank",
        [Measure("offensive_rebound_pct", "ORB%", "ORB%", "pct")],
        False,
        "The share of his team's misses each player rebounded while on the floor, "
        "over his whole season.",
    ),
    Area(
        "defensive_rebounding",
        "Defensive rebounding",
        "defensive_rebound_pct",
        "defensive_rebound_pct_rank",
        [Measure("defensive_rebound_pct", "DRB%", "DRB%", "pct")],
        True,
        f"The share of opponents' misses each player rebounded while on the floor; {_FILM}",
    ),
    Area(
        "free_throws",
        "Getting to the line",
        "free_throw_rate",
        "free_throw_rate_rank",
        [Measure("free_throw_rate", "FT rate", "FT rate (player)", "ratio")],
        False,
        "Free throw attempts per field goal attempt, over each player's whole season.",
    ),
    Area(
        "playmaking",
        "Playmaking",
        "assist_pct",
        "assist_pct_rank",
        [Measure("assist_pct", "AST%", "AST%", "pct")],
        False,
        "The share of teammates' baskets each player assisted while on the floor, "
        "over his whole season.",
    ),
    Area(
        "disruption",
        "Disruption",
        "opp_turnover_pct",
        "opp_turnover_pct_rank",
        [
            Measure("steal_pct", "STL%", "STL%", "pct"),
            Measure("block_pct", "BLK%", "BLK%", "pct"),
        ],
        True,
        f"Steal and block rates count the plays a defender finishes, not the ones he "
        f"prevents; {_FILM}",
    ),
    Area(
        "on_off",
        "Defense on/off (estimate)",
        "defensive_rating",
        "defensive_rating_rank",
        [Measure("def_on_minus_off", "On minus off", "Def. on/off", "signed")],
        True,
        "An estimate, only for 500+ minutes with one team from 1996-97 (below 0: "
        "fewer points allowed with him on); it is noisy, moves with lineups and "
        "teammates, and doesn't replace film.",
    ),
    Area(
        "fouling",
        "Fouling",
        "opp_free_throw_rate",
        "opp_free_throw_rate_rank",
        [Measure("fouls_per_36", "Fouls per 36", "PF/36", "num")],
        True,
        f"Personal fouls per 36 minutes, which feed opponents' free throws; {_FILM}",
    ),
]


def driver_measures() -> list[str]:
    """Every player column the areas read, once each, in area order."""
    cols: list[str] = []
    for area in AREAS:
        for m in area.measures:
            if m.col not in cols:
                cols.append(m.col)
    return cols
