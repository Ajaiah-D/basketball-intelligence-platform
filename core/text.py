"""Text matching shared by every search box, so "jokic" finds "Jokić" the same
way on every page."""

from __future__ import annotations

import unicodedata

# Letters that are their own code point rather than a base letter plus an
# accent, so NFKD leaves them whole and the ASCII step would drop them
# ("Łukasz" would fold to "ukasz" and "lukasz" would never find it). Mapped
# to the plain spelling a reader would type. Lower case only: fold() lowers
# the text first.
_OWN_LETTERS = str.maketrans(
    {
        "ł": "l",
        "ø": "o",
        "đ": "d",
        "ð": "d",
        "ħ": "h",
        "ı": "i",
        "ŀ": "l",
        "ß": "ss",
        "æ": "ae",
        "œ": "oe",
        "þ": "th",
    }
)


def fold(text: object) -> str:
    """Lower case, accents dropped, ASCII only: the form search compares in.

    Both sides of a match must go through this one function. DuckDB's
    strip_accents() is not a substitute: it keeps "ł" and "ø", which this
    turns into "l" and "o", so a needle folded here would miss a name folded
    there.
    """
    lowered = str(text).lower().translate(_OWN_LETTERS)
    return unicodedata.normalize("NFKD", lowered).encode("ascii", "ignore").decode()
