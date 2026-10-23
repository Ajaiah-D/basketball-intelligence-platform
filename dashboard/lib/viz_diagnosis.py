"""Plotly charts for the diagnosis views (the Teams page's league-ranks
profile), in the house style of viz.py and built on its _layout.

Kept apart from viz.py, which is already ~1,000 lines.
"""

from __future__ import annotations

import textwrap
from collections.abc import Mapping
from typing import Any

import pandas as pd
import plotly.graph_objects as go

from core.fmt import ordinal

from . import diagnosis, glossary
from . import theme as T
from .viz import _empty, _layout

# The profile's diverging scale: the bottom of the league (red) through a
# neutral gray to the top (green). Colour only encodes the percentile; no
# label calls a stat good or bad. The neutral sits between MUTED and BASELINE, darker than MUTED, so
# a median bar recedes and stays apart from the unjudged style rows, which
# are MUTED.
PROFILE_NEUTRAL = "#605f5b"
PROFILE_STYLE = T.MUTED

# Each profile stat's printed value. The marts keep rates on a 0-100 scale;
# a "%" goes on the shares, and the per-100 rates (ratings, pace, free throw
# rate) print as plain numbers.
_PLAIN = {
    "offensive_rating",
    "defensive_rating",
    "pace",
    "free_throw_rate",
    "opp_free_throw_rate",
}

# One bar row's height in px, header rows included. With the bargap below
# the bars come out about 22px thick: under the 24px cap, with air between,
# and tall enough that plotly doesn't shrink an 11px label set inside one.
_ROW_PX = 28
# Bars at or past this percentile carry their label inside, in white; the
# shorter ones carry it just past the tip. At phone width a bar this long
# still fits "104.2 · #1 most".
_INSIDE_FROM = 55
# The last-ranked team's bar (percentile 0) still draws a sliver, so the row
# reads as a bar at the far left rather than a missing one. The hover and
# label carry the real rank.
_STUB = 1.0


def _hex_rgb(color: str) -> tuple[int, int, int]:
    c = color.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def _mix(a: str, b: str, t: float) -> str:
    """The colour t of the way from a to b (t in 0..1)."""
    ra, ga, ba = _hex_rgb(a)
    rb, gb, bb = _hex_rgb(b)
    r, g, b_ = (round(x + (y - x) * t) for x, y in ((ra, rb), (ga, gb), (ba, bb)))
    return f"#{r:02x}{g:02x}{b_:02x}"


def percentile_color(pctile: float) -> str:
    """The profile bar colour for a league percentile: T.CRITICAL at 0,
    the neutral gray at 50, T.GOOD at 100, blended in between."""
    p = min(max(float(pctile), 0.0), 100.0)
    if p <= 50:
        return _mix(T.CRITICAL, PROFILE_NEUTRAL, p / 50)
    return _mix(PROFILE_NEUTRAL, T.GOOD, (p - 50) / 50)


def format_value(key: str, value: float) -> str:
    """A profile stat's value as the chart prints it ("56.1%", "117.6")."""
    return f"{value:.1f}" if key in _PLAIN else f"{value:.1f}%"


def _style_rank(rank: int, league_size: int) -> str:
    """'#3 most' / '#2 least': an unjudged stat's place from whichever end
    is nearer, since neither end is the good one (rank 1 = the most)."""
    from_least = league_size + 1 - rank
    return f"#{rank} most" if rank <= from_least else f"#{from_least} least"


def _missing(value: Any) -> bool:
    return value is None or bool(pd.isna(value))


def _hover_term(term: str) -> str:
    """The glossary entry, wrapped for a hover box (plotly doesn't wrap)."""
    text = glossary.TERMS.get(term, "")
    return "<br>".join(textwrap.wrap(text, 52))


def profile_chart(profile_row: Mapping[str, Any], league_size: int = 30) -> go.Figure:
    """Where one team ranks in the league: a horizontal bar per
    diagnosis.PROFILE_STATS row, grouped under Offense / Defense / Style
    labels, its length the league percentile (0-100, right = better: the
    mart has already flipped the lower-is-better stats).

    Judged stats run from T.CRITICAL through gray to T.GOOD and print
    "value · #rank". Unjudged ones (pace, 3-pt rate) are MUTED and print
    "#n most/least", since more of them is a choice, not a strength. A
    stat with no percentile (an early season without the inputs) has no
    row, and a group with none has no label. `league_size` is the number
    of teams that season, for the "least" count."""
    ys: list[str] = []
    ticks: list[str] = []
    xs: list[float | None] = []
    colors: list[str] = []
    texts: list[str] = []
    positions: list[str] = []
    font_colors: list[str] = []
    hovers: list[str] = []

    group = None
    for stat in diagnosis.PROFILE_STATS:
        value: Any = profile_row.get(stat.key)
        rank: Any = profile_row.get(f"{stat.key}_rank")
        pctile: Any = profile_row.get(f"{stat.key}_pctile")
        if _missing(value) or _missing(rank) or _missing(pctile):
            continue
        if stat.group != group:
            group = stat.group
            # A header row: a category with no bar, its tick the group name.
            ys.append(f"group:{group}")
            ticks.append(f'<b><span style="color:{T.INK}">{group.upper()}</span></b>')
            xs.append(None)
            colors.append(PROFILE_NEUTRAL)
            texts.append("")
            positions.append("none")
            font_colors.append(T.INK_2)
            hovers.append("")

        p = float(pctile)
        r = int(rank)
        shown = format_value(stat.key, float(value))
        if stat.judged:
            place = f"#{r}"
            color = percentile_color(p)
            standing = f"#{r} of {league_size} · {ordinal(round(p))} percentile"
        else:
            place = _style_rank(r, league_size)
            color = PROFILE_STYLE
            standing = f"{place} of {league_size} · style: more is neither better nor worse"
        inside = p >= _INSIDE_FROM
        ys.append(stat.key)
        ticks.append(stat.label)
        xs.append(max(p, _STUB))
        colors.append(color)
        texts.append(f"{shown} · {place}")
        positions.append("inside" if inside else "outside")
        font_colors.append(T.INK if inside else T.INK_2)
        hovers.append(
            f"<b>{stat.label}</b> {shown}<br>{standing}"
            f'<br><span style="color:{T.MUTED}">{_hover_term(stat.term)}</span>'
        )

    if all(x is None for x in xs):
        return _empty("No league ranks for this team-season")

    fig = go.Figure()
    fig.add_bar(
        y=ys,
        x=xs,
        orientation="h",
        marker={"color": colors, "cornerradius": 4},
        text=texts,
        textposition=positions,
        insidetextanchor="end",
        textangle=0,
        textfont={"color": font_colors, "size": 11},
        cliponaxis=False,
        hovertext=hovers,
        hovertemplate="%{hovertext}<extra></extra>",
        showlegend=False,
    )
    # The league median. Dashed, unlike the hairline grid, so it reads as
    # the reference the bars are measured against.
    fig.add_vline(x=50, line_color=T.MUTED, line_width=1, line_dash="dash")
    fig.add_annotation(
        x=50,
        y=1,
        xref="x",
        yref="paper",
        yanchor="bottom",
        text="league median",
        showarrow=False,
        font={"color": T.MUTED, "size": 11},
    )
    fig.update_layout(
        **_layout(
            height=_ROW_PX * len(ys) + 90,
            bargap=0.2,
            showlegend=False,
            margin={"l": 8, "r": 8, "t": 24, "b": 8},
            xaxis={
                # Headroom past 100 for the labels outside the shorter bars.
                "range": [0, 130],
                "tickvals": [0, 25, 50, 75, 100],
                "gridcolor": T.GRID,
                "tickfont": {"color": T.MUTED},
                "title": {
                    "text": "League percentile (100 = best)",
                    "font": {"color": T.MUTED, "size": 11},
                },
                "fixedrange": True,
                "automargin": True,
                "zeroline": False,
            },
            yaxis={
                # Header rows have no bar, so the categories are pinned
                # explicitly rather than inferred from the data.
                "categoryorder": "array",
                "categoryarray": ys,
                "tickvals": ys,
                "ticktext": ticks,
                "tickfont": {"color": T.INK_2},
                "autorange": "reversed",
                "fixedrange": True,
                "automargin": True,
                "ticksuffix": "  ",
            },
        )
    )
    return fig
