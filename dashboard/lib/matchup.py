"""One game's matchup on a single line, with the model's favourite marked,
and its tip-off time.

The Schedule page's upcoming games and the Predictions page share this
format, so a pick reads the same everywhere: `NYK @ BOS · 65%`, the
favourite bold in its team colour. Each abbreviation appears once and the
probability once - the bold says whose percentage it is.
"""

from __future__ import annotations

import html
from zoneinfo import ZoneInfo

import pandas as pd

from core.constants import HOME_PICK_THRESHOLD

from . import theme as T
from .tables import is_missing

# Below this chance for the favourite, the line says "toss-up" instead of a
# percentage and marks neither team: 52% is a lean the model's own error
# swamps, and a bold team would read as a call.
TOSS_UP_BELOW = 55

# Tip-offs are shown in US Eastern time, the league's own clock.
EASTERN = ZoneInfo("America/New_York")


def favourite_pct(home_win_prob: float) -> tuple[bool, int]:
    """(is the home team the favourite, the favourite's whole-number
    percentage). A coin flip counts as a home pick, the same rule the
    Predictions page grades with (HOME_PICK_THRESHOLD)."""
    home_pct = round(float(home_win_prob) * 100)
    home_fav = float(home_win_prob) >= HOME_PICK_THRESHOLD
    return home_fav, home_pct if home_fav else 100 - home_pct


def favourite_matchup_html(away: str, home: str, home_win_prob: float | None) -> str:
    """'NYK @ BOS · 65%' as HTML, the favourite bold in its team colour;
    'NYK @ BOS · toss-up' when the favourite is under TOSS_UP_BELOW percent;
    'NYK @ BOS' when there is no prediction. All text is escaped."""
    away_html, home_html = html.escape(away), html.escape(home)
    if home_win_prob is None or is_missing(home_win_prob):
        return f"{away_html} @ {home_html}"
    home_fav, pct = favourite_pct(home_win_prob)
    if pct < TOSS_UP_BELOW:
        return f"{away_html} @ {home_html} · toss-up"
    if home_fav:
        home_html = f'<b style="color:{T.team_color(home)}">{home_html}</b>'
    else:
        away_html = f'<b style="color:{T.team_color(away)}">{away_html}</b>'
    return f"{away_html} @ {home_html} · {pct}%"


def tipoff_label(tipoff_utc) -> str:
    """'7:00 PM ET' for a tip-off stored as a zone-less UTC time (as
    stg_schedule has it); 'TBD' when it isn't known."""
    if tipoff_utc is None or is_missing(tipoff_utc):
        return "TBD"
    t = pd.Timestamp(tipoff_utc).tz_localize("UTC").tz_convert(EASTERN)
    return f"{t.hour % 12 or 12}:{t.minute:02d} {'AM' if t.hour < 12 else 'PM'} ET"
