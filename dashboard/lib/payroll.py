"""Plain-English reading of payrolls against the league's lines - the words
and colors the Finances page puts next to its numbers.

Pure functions over the mart's rows, no Streamlit, so every sentence the
page can publish is pinned by tests/test_payroll_text.py. The first version
of the page showed bare figures and "Over cap" on 28-30 teams a season with
no word that a soft cap makes that normal; this module exists so no number
reaches the page without the sentence that says what it means.
"""

from __future__ import annotations

import pandas as pd

from . import theme as T

# Over the cap is normal, so it gets a quiet gray: in a season where all 30
# teams are over it, a bright neutral would outweigh the handful of
# taxpayers the snapshot exists to point out.
OVER_CAP_GRAY = "#5f5e59"

# (mart column, label, color), lowest line first. The same color means the
# same line everywhere: both charts, the status card and the bar colors.
LINES = [
    ("salary_cap", "Salary cap", OVER_CAP_GRAY),
    ("luxury_tax", "Luxury tax", T.SERIES[3]),
    ("first_apron", "First apron", T.SERIES[1]),
    ("second_apron", "Second apron", T.CRITICAL),
]
_LINE_PHRASES = {"salary_cap": "salary cap", "luxury_tax": "luxury tax line",
                 "first_apron": "first apron", "second_apron": "second apron"}

# Highest first: over the second apron is also over everything below it.
_TIERS = [
    ("over_second_apron", "second_apron", "Over 2nd apron"),
    ("over_first_apron", "first_apron", "Over 1st apron"),
    ("over_tax", "luxury_tax", "Over tax"),
    ("over_cap", "salary_cap", "Over cap"),
]
_COLOR = {col: color for col, _, color in LINES}


def _true(value) -> bool:
    # over_tax/over_*_apron are NA, not False, before that line existed -
    # and NA has no truth value.
    return bool(pd.notna(value) and value)


def _unreliable(row) -> bool:
    return _true(row["payroll_likely_incomplete"]) or pd.isna(row["team_payroll"])


def bracket(row) -> tuple[str, str]:
    """(label, color) for the highest line this team-season's payroll crossed."""
    if _unreliable(row):
        return "Data incomplete", T.MUTED
    for flag, col, label in _TIERS:
        if _true(row[flag]):
            return label, _COLOR[col]
    return "Under cap", T.GOOD


def money(value: float) -> str:
    if abs(value) >= 1_000_000:
        return f"${value / 1e6:,.1f}M"
    return f"${value / 1e3:,.0f}K"


def ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def reliable(league_df: pd.DataFrame) -> pd.DataFrame:
    """Rows whose payroll can be published as a real number."""
    # astype(bool): `~` on an object column of Python bools is bitwise int
    # negation (~True == -2), not a boolean NOT.
    flagged = league_df["payroll_likely_incomplete"].fillna(True).astype(bool)
    keep = league_df["team_payroll"].notna() & ~flagged
    return league_df[keep]


def league_rank(league_df: pd.DataFrame, team_abbreviation: str) -> tuple[int, int] | None:
    """(rank, out of) by payroll, highest = 1, among reliable rows only."""
    ok = reliable(league_df).sort_values("team_payroll", ascending=False).reset_index(drop=True)
    hit = ok.index[ok["team_abbreviation"] == team_abbreviation]
    return (int(hit[0]) + 1, len(ok)) if len(hit) else None


def _next_line_up(row, col: str) -> str | None:
    cols = [c for c, _, _ in LINES]
    for higher in cols[cols.index(col) + 1:]:
        if pd.notna(row[higher]):
            return higher
    return None


def position_phrase(row) -> str:
    """How far over the highest line crossed, and how far under the next one."""
    pay = row["team_payroll"]
    for flag, col, _ in _TIERS:
        if _true(row[flag]):
            phrase = f"{money(pay - row[col])} over the {_LINE_PHRASES[col]}"
            higher = _next_line_up(row, col)
            if higher:
                phrase += f" and {money(row[higher] - pay)} under the {_LINE_PHRASES[higher]}"
            return phrase
    return f"{money(row['salary_cap'] - pay)} under the salary cap"


def league_summary(league_df: pd.DataFrame, season: str) -> str:
    ok = reliable(league_df)
    n = len(ok)
    parts = [f"{int(ok['over_cap'].map(_true).sum())} of {n} teams were over the salary cap"]
    for flag, col, phrase in [("over_tax", "luxury_tax", "luxury tax line"),
                              ("over_first_apron", "first_apron", "first apron"),
                              ("over_second_apron", "second_apron", "second apron")]:
        if ok[col].notna().any():
            parts.append(f"{int(ok[flag].map(_true).sum())} over the {phrase}")
    text = f"In {season}, {_join(parts)}."
    missing = len(league_df) - n
    if missing:
        text += (f" {missing} team{'s have' if missing > 1 else ' has'} no reliable "
                 "figure for this season.")
    return text


def team_summary(row, team_name: str, rank: tuple[int, int] | None,
                 contracts: pd.DataFrame | None) -> str:
    if _unreliable(row):
        return f"There's no reliable payroll figure for the {team_name} in {row['season']}."
    text = f"In {row['season']} the {team_name} spent {money(row['team_payroll'])}"
    if rank:
        place = "highest" if rank[0] == 1 else f"{ordinal(rank[0])}-highest"
        text += f", the {place} payroll of {rank[1]} teams"
    text += f". That's {position_phrase(row)}."
    if contracts is not None and len(contracts) >= 3:
        top = contracts.nsmallest(3, "salary_rank")
        text += (f" Their three biggest contracts ({_join(top['player'].tolist())}) "
                 f"made up {top['share_of_payroll'].sum():.0%} of the payroll.")
    return text


def freshness_text(fetched_at, latest_payroll_season: str, latest_cap_season: str) -> str:
    if fetched_at is None or pd.isna(fetched_at):
        text = (f"Salary data covers through {latest_payroll_season} "
                "(update date not recorded in this copy).")
    else:
        ts = pd.Timestamp(fetched_at)
        text = (f"Salary data updated {ts:%b} {ts.day}, {ts.year} · covers through "
                f"{latest_payroll_season}.")
    if latest_cap_season > latest_payroll_season:
        text += f" {latest_cap_season} payrolls aren't loaded yet."
    return text


HOW_TO_READ = """
**Salary cap** - the limit on signing other teams' free agents. It's a *soft*
cap: teams can go over it to re-sign their own players, use exceptions and
add minimum contracts, which is why nearly every team is over it. Being over
the cap is normal.

**Luxury tax line** - where spending starts to cost real money. A team over
it at the end of the regular season pays a tax on every dollar above it,
starting at $1.50 per dollar and climbing the further over it goes, with
higher rates for teams that pay it year after year.

**First apron** (2023-24 on) - a team over it loses roster-building tools,
such as taking back more salary than it sends out in a trade.

**Second apron** (2023-24 on) - the strictest line. A team over it can't
combine salaries in a trade or use its mid-level exception, and its
first-round pick seven years out gets frozen.
"""

METHOD_NOTE = (
    "Payroll is the sum of the salaries Basketball-Reference lists for each team's "
    "season: the players it finished the season with, plus anyone on a 10-day "
    "contract along the way at the amount paid. The NBA's official tax bill also "
    "counts money still owed to waived players and only the part of a traded "
    "player's salary each team actually paid, so a team within a few million of "
    "a line may have finished on the other side of it. League cap, tax and apron "
    "figures are the NBA's own."
)
