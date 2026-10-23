"""The rules behind the Teams page's diagnosis views: which stats make up a
team's strengths-and-weaknesses profile, the "Best at / Worst at" line, the
ten "who drives it" areas, and the one-line read each area writes from its
numbers.

Pure: no Streamlit and no SQL. The numbers come from
dashboard/lib/data/diagnosis.py (mart_team_profile for the team,
team_drivers() for the rotation); everything here only words them.

The reads are deterministic (ties break on the player's name) and say no
more than the numbers do: "most of" needs half the attempts, and every
defensive read calls itself an estimate, because box scores show defense
far worse than offense.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any, NamedTuple

import pandas as pd


class ProfileStat(NamedTuple):
    """One bar of the profile chart: a mart_team_profile column (its rank
    and percentile are `<key>_rank` and `<key>_pctile`)."""

    key: str
    label: str
    group: str  # "Offense" | "Defense" | "Style"
    term: str  # the glossary.TERMS entry for its hover


# The spec's order. Style (pace) is shown but never judged.
PROFILE_STATS: list[ProfileStat] = [
    ProfileStat("offensive_rating", "Offensive rating", "Offense", "Offensive rating"),
    ProfileStat("effective_fg_pct", "eFG%", "Offense", "eFG%"),
    ProfileStat("three_pt_pct", "3P%", "Offense", "3P%"),
    ProfileStat("three_pt_rate", "3-pt rate", "Offense", "3-pt rate"),
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
    ProfileStat("pace", "Pace", "Style", "Pace"),
]


def _missing(value: Any) -> bool:
    """None, NaN or pd.NA."""
    return value is None or bool(pd.isna(value))


def _in_sentence(label: str) -> str:
    """'Offensive rating' -> 'offensive rating' mid-sentence; abbreviations
    ('eFG%', 'FT rate', '3P%') keep their case."""
    if len(label) > 1 and label[0].isupper() and not label[1].isupper():
        return label[0].lower() + label[1:]
    return label


def summary_line(profile_row: Mapping[str, Any] | None, n: int = 3) -> str:
    """The "Best at: 3P% (#2), ... · Worst at: turnover rate (#30), ..."
    line for one mart_team_profile row: the n best and n worst league ranks
    among the Offense and Defense stats (style is not good or bad). Nulls
    are skipped, rank ties keep the profile's order, and no stat appears on
    both sides. "" when nothing is ranked."""
    if profile_row is None:
        return ""
    ranked = []
    for order, stat in enumerate(PROFILE_STATS):
        if stat.group == "Style":
            continue
        rank = profile_row.get(f"{stat.key}_rank")
        if rank is not None and not _missing(rank):
            ranked.append((int(rank), order, stat))
    if not ranked:
        return ""
    ranked.sort(key=lambda item: (item[0], item[1]))
    best_count = min(n, (len(ranked) + 1) // 2)
    worst_count = min(n, len(ranked) - best_count)
    best = ranked[:best_count]
    worst = list(reversed(ranked[len(ranked) - worst_count :])) if worst_count else []

    def names(items: list) -> str:
        return ", ".join(f"{_in_sentence(stat.label)} (#{rank})" for rank, _o, stat in items)

    parts = [f"Best at: {names(best)}"]
    if worst:
        parts.append(f"Worst at: {names(worst)}")
    return " · ".join(parts)


class Area(NamedTuple):
    """One "who drives it" area: the team stat it explains and the player
    measures (team_drivers() columns) that explain it."""

    key: str
    label: str
    team_stat: str  # a PROFILE_STATS key
    team_rank_col: str
    player_cols: list[tuple[str, str, bool]]  # (column, label, higher_is_better)
    defensive: bool
    caption: str


_RATES = "A traded player's rates cover his whole season, not just this team."
_FILM = (
    "Box-score rates show defensive activity, not the whole of defense; they don't replace film."
)

AREAS: list[Area] = [
    Area(
        "scoring",
        "Scoring efficiency",
        "effective_fg_pct",
        "effective_fg_pct_rank",
        [("true_shooting_pct", "true shooting", True), ("usage_pct", "usage", True)],
        False,
        f"True shooting against how much of the offense each player uses. {_RATES}",
    ),
    Area(
        "three_point",
        "3-point shooting",
        "three_pt_pct",
        "three_pt_pct_rank",
        [("three_pa_per_game", "3PA per game", True), ("fg3_pct", "3P%", True)],
        False,
        "Three-point volume and accuracy for this team only, against the league median.",
    ),
    Area(
        "ball_security",
        "Ball security",
        "turnover_pct",
        "turnover_pct_rank",
        [("turnover_pct", "turnover rate", False), ("usage_pct", "usage", True)],
        False,
        f"Turnover rate is lower-is-better; high-usage players turn it over more. {_RATES}",
    ),
    Area(
        "offensive_rebounding",
        "Offensive rebounding",
        "offensive_rebound_pct",
        "offensive_rebound_pct_rank",
        [("offensive_rebound_pct", "offensive rebound rate", True)],
        False,
        f"The share of his team's misses each player rebounds while on the floor. {_RATES}",
    ),
    Area(
        "defensive_rebounding",
        "Defensive rebounding",
        "defensive_rebound_pct",
        "defensive_rebound_pct_rank",
        [("defensive_rebound_pct", "defensive rebound rate", True)],
        True,
        _FILM,
    ),
    Area(
        "free_throws",
        "Getting to the line",
        "free_throw_rate",
        "free_throw_rate_rank",
        [("free_throw_rate", "free throw rate", True)],
        False,
        f"Free throw attempts per field goal attempt. {_RATES}",
    ),
    Area(
        "playmaking",
        "Playmaking",
        "assist_pct",
        "assist_pct_rank",
        [("assist_pct", "assist rate", True)],
        False,
        f"The share of teammates' baskets each player assisted while on the floor. {_RATES}",
    ),
    Area(
        "disruption",
        "Disruption",
        "opp_turnover_pct",
        "opp_turnover_pct_rank",
        [("steal_pct", "steal rate", True), ("block_pct", "block rate", True)],
        True,
        _FILM,
    ),
    Area(
        "on_off",
        "Defense on/off (estimate)",
        "defensive_rating",
        "defensive_rating_rank",
        [("def_on_minus_off", "on minus off", False)],
        True,
        "An estimate from published ratings, for 500+ minutes with one team: it moves "
        "with lineups and teammates, and it doesn't replace film.",
    ),
    Area(
        "fouling",
        "Fouling",
        "opp_free_throw_rate",
        "opp_free_throw_rate_rank",
        [("fouls_per_36", "fouls per 36", False)],
        True,
        "Fouls per 36 minutes, which feed the opponents' free throws; counting fouls "
        "doesn't replace film.",
    ),
]


def driver_measures() -> list[str]:
    """Every player column the areas read, once each, in area order."""
    cols: list[str] = []
    for area in AREAS:
        for col, _label, _higher in area.player_cols:
            if col not in cols:
                cols.append(col)
    return cols


# --- The one-line read ------------------------------------------------------------

_SUFFIXES = {"Jr.", "Jr", "Sr.", "Sr", "II", "III", "IV"}

# How each measure prints: a 0-100 percentage, a ratio (.412) or a number.
_PERCENT = {
    "true_shooting_pct",
    "usage_pct",
    "fg3_pct",
    "turnover_pct",
    "offensive_rebound_pct",
    "defensive_rebound_pct",
    "assist_pct",
    "steal_pct",
    "block_pct",
}
_RATIO = {"free_throw_rate"}

_DEFENSE_NOTE = " - a box-score estimate of defense"
_ON_OFF_NOTE = " - an estimate; see the caption."
# The smallest on/off gap worth naming a player for, in points per 100.
_ON_OFF_MIN_GAP = 1.0
# The reads name regulars only: the rotation's 10-game floor lets in a
# player whose few minutes give him the team's "best" rate by accident.
REGULAR_MIN_MPG = 15.0


def _short_names(names: list[str]) -> list[str]:
    """Surnames for a sentence ("Tatum", "Jackson Jr."), or the full names
    where two surnames would read the same."""

    def surname(name: str) -> str:
        parts = name.split()
        if len(parts) >= 3 and parts[-1] in _SUFFIXES:
            return " ".join(parts[-2:])
        return parts[-1] if parts else name

    short = [surname(n) for n in names]
    return [n if short.count(s) > 1 else s for n, s in zip(names, short, strict=True)]


def _fmt(col: str, value: float) -> str:
    if col in _PERCENT:
        return f"{value:.1f}%"
    if col in _RATIO:
        return f"{value:.3f}".removeprefix("0")
    return f"{value:.1f}"


def _median(rows: pd.DataFrame, col: str) -> float | None:
    name = f"{col}_league_median"
    if name not in rows.columns:
        return None
    values = rows[name].dropna()
    return None if values.empty else float(values.iloc[0])


def _ranked(rows: pd.DataFrame, col: str, higher: bool) -> pd.DataFrame:
    """The players with a value for `col`, best first, ties by name."""
    if col not in rows.columns:
        return rows.iloc[0:0]
    have = rows[rows[col].notna()].copy()
    have["_sort"] = -have[col].astype(float) if higher else have[col].astype(float)
    return have.sort_values(["_sort", "player"], kind="mergesort")


def _regulars(rows: pd.DataFrame) -> pd.DataFrame:
    """The rows with REGULAR_MIN_MPG+ minutes a game, or every row when
    none qualify (or the frame has no minutes)."""
    if "minutes_per_game" not in rows.columns:
        return rows
    regulars = rows[rows["minutes_per_game"].fillna(0) >= REGULAR_MIN_MPG]
    return rows if regulars.empty else regulars


def _fallback(area: Area, team: str) -> str:
    return f"Not enough data on {team}'s {area.label.lower()} this season."


def _three_point_read(team: str, rows: pd.DataFrame) -> str | None:
    if "team_three_pa_share" not in rows.columns:
        return None
    top = _ranked(rows[rows["team_three_pa_share"].fillna(0) > 0], "team_three_pa_share", True)
    top = top.head(2)
    if top.empty:
        return None
    names = _short_names(top["player"].tolist())
    share = round(100 * float(top["team_three_pa_share"].sum()))
    who = " and ".join(names)
    if share >= 50:
        lead = f"Most of {team}'s threes come from {who}"
    elif len(names) == 1:
        lead = f"{team}'s most frequent three-point shooter is {who}"
    else:
        lead = f"{team}'s most frequent three-point shooters are {who}"
    sentence = f"{lead} ({share}% of attempts)"

    median = _median(rows, "fg3_pct")
    pcts = top["fg3_pct"].tolist() if "fg3_pct" in top.columns else []
    if median is None or any(_missing(p) for p in pcts):
        return sentence + "."
    above = [float(p) > median for p in pcts]
    if len(names) == 1:
        side = "above" if above[0] else "below"
        return f"{sentence}, {side} the league median at {float(pcts[0]):.1f}%."
    if all(above):
        floor = math.floor(min(float(p) for p in pcts))
        return f"{sentence}, both above league median at {floor}%+."
    if not any(above):
        return f"{sentence}, both below the league median ({median:.1f}%)."
    sides = ["above" if a else "below" for a in above]
    return (
        f"{sentence}, {names[0]} {sides[0]} and {names[1]} {sides[1]} "
        f"the league median ({median:.1f}%)."
    )


def _on_off_read(team: str, rows: pd.DataFrame) -> str:
    ranked = _ranked(rows, "def_on_minus_off", False)
    if ranked.empty:
        return (
            f"No {team} player has an on/off estimate this season; it needs 500+ "
            "minutes for one team, from 1996-97."
        )
    best = ranked.iloc[0]
    gap = float(best["def_on_minus_off"])
    if gap > -_ON_OFF_MIN_GAP:
        return f"No {team} player improves its defense by a point per 100 or more{_ON_OFF_NOTE}"
    name = _short_names([best["player"]])[0]
    return f"{team} defends {-gap:.1f} points per 100 better with {name} on the floor{_ON_OFF_NOTE}"


def _leader_read(area: Area, team: str, rows: pd.DataFrame) -> str | None:
    col, label, higher = area.player_cols[0]
    median = _median(rows, col)
    ranked = _ranked(rows, col, higher)
    if ranked.empty or median is None:
        return None
    leader = ranked.iloc[0]
    name = _short_names([leader["player"]])[0]
    values = ranked[col].astype(float)
    better = int((values > median).sum() if higher else (values < median).sum())
    most = "highest" if higher else "lowest"
    note = _DEFENSE_NOTE if area.defensive else ""
    return (
        f"{name} has {team}'s {most} {label} ({_fmt(col, float(leader[col]))}; "
        f"league median {_fmt(col, median)}); {better} of {len(ranked)} regulars "
        f"beat it{note}."
    )


def _disruption_read(area: Area, team: str, rows: pd.DataFrame) -> str | None:
    leaders = []  # (name, "steal rate (1.9%; median 1.5%)")
    for col, label, higher in area.player_cols:
        median = _median(rows, col)
        ranked = _ranked(rows, col, higher)
        if ranked.empty or median is None:
            continue
        leader = ranked.iloc[0]
        name = _short_names([leader["player"]])[0]
        value = _fmt(col, float(leader[col]))
        leaders.append((name, f"{label} ({value}; median {_fmt(col, median)})"))
    if not leaders:
        return None
    first_name, first = leaders[0]
    if len(leaders) == 1:
        return f"{first_name} leads {team} in {first}{_DEFENSE_NOTE}."
    second_name, second = leaders[1]
    if second_name == first_name:
        return f"{first_name} leads {team} in {first} and {second}{_DEFENSE_NOTE}."
    return f"{first_name} leads {team} in {first}, {second_name} in {second}{_DEFENSE_NOTE}."


def driver_read(area: Area, team_label: str, rows: pd.DataFrame) -> str:
    """One plain sentence (25 words at most) on who drives `area` for the
    team, from its team_drivers() rows, naming regulars only (15+ minutes
    a game); a fallback sentence when the data is too thin to say
    anything."""
    rows = _regulars(rows)
    if area.key == "on_off":
        return _on_off_read(team_label, rows)
    if area.key == "three_point":
        read = _three_point_read(team_label, rows)
    elif area.key == "disruption":
        read = _disruption_read(area, team_label, rows)
    else:
        read = _leader_read(area, team_label, rows)
    return read if read is not None else _fallback(area, team_label)
