"""A player's bio line and the All players position filter, as plain
functions over the mart_player_bio row (data.players.player_bio).

The NBA labels positions broadly: G, F, C, or a pair such as G-F for a
player who plays both. The filter treats a pair as both of its letters, so a
G-F is listed under guards and under forwards.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

SEP = " · "


def _missing(value) -> bool:
    return value is None or (not isinstance(value, str) and pd.isna(value))


def height_text(height: str | None) -> str | None:
    """'6-6' (the NBA's form) as 6'6", or None when there is no height."""
    if not isinstance(height, str) or "-" not in height:
        return None
    feet, inches = height.split("-", 1)
    return f"{feet}'{inches}\""


def draft_text(year, rnd, number) -> str:
    """'2017 R1 #3', 'Undrafted' when there is no draft year, or just the
    year for an old record with no pick."""
    if _missing(year):
        return "Undrafted"
    if _missing(rnd) or _missing(number):
        return f"{int(year)} draft"
    return f"{int(year)} R{int(rnd)} #{int(number)}"


def age_now(birthdate, today: date) -> int | None:
    """Age in whole years on `today`, or None without a birthdate."""
    if _missing(birthdate):
        return None
    born = pd.Timestamp(birthdate).date()
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))


def bio_line(b: dict, age: int | None) -> str:
    """Position · height · weight · age · birthdate · country · college ·
    draft, leaving out whatever is missing. The draft always shows, since
    "Undrafted" is itself a fact."""
    parts: list[str] = []
    if not _missing(b.get("position")):
        parts.append(str(b["position"]))
    height = height_text(b.get("height"))
    if height:
        parts.append(height)
    if not _missing(b.get("weight")):
        parts.append(f"{int(b['weight'])} lb")
    if age is not None and not _missing(age):
        parts.append(f"Age {int(age)}")
    if not _missing(b.get("birthdate")):
        born = pd.Timestamp(b["birthdate"])
        parts.append(f"Born {born.strftime('%b')} {born.day}, {born.year}")
    for key in ("country", "college"):
        if not _missing(b.get(key)):
            parts.append(str(b[key]))
    parts.append(draft_text(b.get("draft_year"), b.get("draft_round"), b.get("draft_number")))
    return SEP.join(parts)


def position_matches(position: str | None, wanted: list[str]) -> bool:
    """Whether a player listed at `position` belongs under the filter's
    `wanted` letters. An empty filter matches everyone, including players
    with no position on record; otherwise those are left out."""
    if not wanted:
        return True
    if not isinstance(position, str) or not position:
        return False
    return any(letter in position.split("-") for letter in wanted)
