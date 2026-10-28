"""Number formats the pages share."""

from __future__ import annotations


def money(value: float) -> str:
    """Dollars, short: "$193.3M" from a million up, "$850K" below."""
    if abs(value) >= 1_000_000:
        return f"${value / 1e6:,.1f}M"
    return f"${value / 1e3:,.0f}K"


def ordinal(n: int) -> str:
    """1 -> "1st", 12 -> "12th", 22 -> "22nd"."""
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def matchup(away: bool, opp: str) -> str:
    """A game's opponent as a box score writes it: "@ BOS" on the road,
    "vs BOS" at home."""
    return f"{'@' if away else 'vs'} {opp}"
