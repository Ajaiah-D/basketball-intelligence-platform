"""Plotly charts for the diagnosis views (the Teams page's league-ranks
profile and player breakdown), in the house style of viz.py and built on
its _layout.

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
# label calls a stat good or bad. The neutral sits between MUTED and
# BASELINE, darker than MUTED, so a median bar recedes and stays apart from
# the unjudged style rows, which are MUTED.
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
# What an unjudged (style) stat's rank counts, from the top: rank 1 is the
# fastest pace, the biggest share of shots from three. The bar says it
# briefly ("#13 in threes"): at phone width a mid-length bar has room for
# neither "42.6% · #13 in threes taken" inside nor past its tip. The hover
# spells it out.
STYLE_RANK_NOUN = {"pace": "fastest", "three_pt_rate": "in threes"}
STYLE_RANK_HOVER = {
    "pace": "fastest",
    "three_pt_rate": "in threes taken (share of shots from three)",
}

# A label goes inside its bar, in white, when it fits there at phone width
# (the narrowest plot: about 1.85px per percentile point, and about 5.6px
# per 11px character); otherwise it sits just past the tip.
_PHONE_PX_PER_POINT = 1.85
_CHAR_PX = 5.6
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


def _fits_inside(pctile: float, label: str) -> bool:
    """Whether `label` fits inside a bar of this length at phone width."""
    return pctile * _PHONE_PX_PER_POINT >= len(label) * _CHAR_PX + 10


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
    "value · #rank". Unjudged ones (pace, 3-pt rate) are MUTED and name
    what their rank counts ("#3 fastest"), since more of them is a style,
    not a ranking from good to bad. A stat with no percentile (an early
    season without the inputs) has no row, and a group with none has no
    label. `league_size` is the number of teams that season, for the
    hover's "#4 of 30"."""
    ys: list[str] = []
    ticks: list[str] = []
    xs: list[float | None] = []
    colors: list[str] = []
    texts: list[str] = []
    positions: list[str] = []
    hovers: list[str] = []
    outside: list[tuple[str, float, str]] = []  # (category, bar end, label)

    group = None
    for stat in diagnosis.PROFILE_STATS:
        value: Any = profile_row.get(stat.key)
        rank: Any = profile_row.get(f"{stat.key}_rank")
        pctile: Any = profile_row.get(f"{stat.key}_pctile")
        if diagnosis.missing(value) or diagnosis.missing(rank) or diagnosis.missing(pctile):
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
            hovers.append("")

        p = float(pctile)
        r = int(rank)
        shown = format_value(stat.key, float(value))
        if stat.judged:
            place = f"#{r}"
            color = percentile_color(p)
            standing = f"#{r} of {league_size} · {ordinal(round(p))} percentile"
        else:
            place = f"#{r} {STYLE_RANK_NOUN.get(stat.key, '')}".rstrip()
            color = PROFILE_STYLE
            counts = STYLE_RANK_HOVER.get(stat.key, "")
            standing = f"#{r} of {league_size} {counts} · a style stat"
        label = f"{shown} · {place}"
        x = max(p, _STUB)
        ys.append(stat.key)
        ticks.append(stat.label)
        xs.append(x)
        colors.append(color)
        texts.append(label)
        if _fits_inside(p, label):
            positions.append("inside")
        else:
            # Drawn as an annotation instead, for its background: plotly's
            # bar text has none, and a label crossing the dashed median
            # line is hard to read without one.
            positions.append("none")
            outside.append((stat.key, x, label))
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
        textfont={"color": T.INK, "size": 11},
        hovertext=hovers,
        hovertemplate="%{hovertext}<extra></extra>",
        showlegend=False,
    )
    # The league median. Dashed, unlike the hairline grid, so it reads as
    # the reference the bars are measured against. Drawn below the bars, so
    # it shows in the gaps between them and never crosses a label set
    # inside one.
    fig.add_vline(x=50, line_color=T.MUTED, line_width=1, line_dash="dash", layer="below")
    for category, x, label in outside:
        fig.add_annotation(
            x=x,
            y=category,
            xanchor="left",
            xshift=4,
            text=label,
            showarrow=False,
            font={"color": T.INK_2, "size": 11},
            bgcolor=T.PAGE,
            borderpad=1,
        )
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
                    "text": "League percentile (100 = first in the league)",
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


# --- The player breakdown ------------------------------------------------------

# One player row's height in px, and the dot diameters: the fewest minutes
# in the rotation get the smallest dot (at the 8px floor for a marker) and
# the most get the largest, the diameter growing with the square root of
# minutes so big minutes don't swamp the chart.
_DRIVER_ROW_PX = 26
_DOT_MIN_PX = 8
_DOT_MAX_PX = 20
# The gap between two measure panels, as a share of the plot width.
_PANEL_GAP = 0.08


def _dot_sizes(minutes: pd.Series) -> list[float]:
    m = minutes.fillna(0).astype(float).clip(lower=0)
    top = float(m.max()) if len(m) else 0.0
    if top <= 0:
        return [float(_DOT_MIN_PX)] * len(m)
    return [_DOT_MIN_PX + (_DOT_MAX_PX - _DOT_MIN_PX) * (v / top) ** 0.5 for v in m]


def _median_of(rows: pd.DataFrame, col: str) -> float | None:
    name = f"{col}_league_median"
    if name not in rows.columns:
        return None
    values = rows[name].dropna()
    return None if values.empty else float(values.iloc[0])


def _panel_range(values: pd.Series, median: float | None) -> list[float]:
    """The x range that holds every value and the median, with a margin so
    the largest dots aren't cut at the edge."""
    points = [float(v) for v in values.dropna()]
    if median is not None:
        points.append(median)
    if not points:
        return [0.0, 1.0]
    lo, hi = min(points), max(points)
    pad = (hi - lo) * 0.08 or max(abs(hi) * 0.1, 0.5)
    return [lo - pad, hi + pad]


def drivers_chart(rows: pd.DataFrame, area: diagnosis.Area, team: str) -> go.Figure:
    """The rotation on one area: a row per player (team_drivers() order,
    most minutes at the top), a dot per measure at his value, sized by his
    minutes for the team and in the team's colour, against a dashed line at
    the league median. An area with two measures gets two panels side by
    side, each on its own axis, sharing the player rows.

    A player with no value for a measure (no on/off estimate, a season
    without the box-score inputs) gets "not available" in that panel
    instead of a dot. No legend: the panels' axis titles name the
    measures."""
    if rows.empty:
        return _empty("No rotation players for this team-season")

    # Row keys: the player id, so two players with one name keep two rows,
    # prefixed so plotly never reads them as numbers.
    ids = [f"p{i}" for i in rows["player_id"]]
    names = rows["player"].tolist()
    sizes = _dot_sizes(rows["minutes"]) if "minutes" in rows.columns else [_DOT_MIN_PX] * len(ids)
    color = T.team_color(team)
    measures = area.measures
    width = (1 - _PANEL_GAP * (len(measures) - 1)) / len(measures)

    fig = go.Figure()
    axes: dict[str, Any] = {}
    for i, m in enumerate(measures):
        suffix = "" if i == 0 else str(i + 1)
        xref = f"x{suffix}"
        values = rows[m.col] if m.col in rows.columns else pd.Series([None] * len(ids))
        median = _median_of(rows, m.col)
        shown = [m.format(v) for v in values]
        med_text = m.format(median) if median is not None else "-"
        hovers = [
            f"<b>{name}</b><br>{m.label} {value} · league median {med_text}"
            f"<br>{_minutes_line(row)}"
            f'<br><span style="color:{T.MUTED}">{_hover_term(m.term)}</span>'
            for name, value, row in zip(names, shown, rows.itertuples(index=False), strict=True)
        ]
        fig.add_scatter(
            x=values.tolist(),
            y=ids,
            xaxis=xref,
            yaxis="y",
            mode="markers",
            marker={
                "size": sizes,
                "color": color,
                # A ring in the page colour keeps overlapping dots apart.
                "line": {"color": T.PAGE, "width": 2},
            },
            hovertext=hovers,
            hovertemplate="%{hovertext}<extra></extra>",
            # The biggest dots at either end of the range stay whole.
            cliponaxis=False,
            showlegend=False,
            name=m.label,
        )
        for pid, value in zip(ids, values, strict=True):
            if diagnosis.missing(value):
                fig.add_annotation(
                    x=0,
                    xref=f"{xref} domain",
                    y=pid,
                    yref="y",
                    xanchor="left",
                    text="not available",
                    showarrow=False,
                    font={"color": T.MUTED, "size": 11},
                )
        if median is not None:
            fig.add_shape(
                type="line",
                x0=median,
                x1=median,
                xref=xref,
                y0=0,
                y1=1,
                yref="paper",
                line={"color": T.MUTED, "width": 1, "dash": "dash"},
                layer="below",
            )
            fig.add_annotation(
                x=median,
                xref=xref,
                y=1,
                yref="paper",
                yanchor="bottom",
                text=f"median {med_text}",
                showarrow=False,
                font={"color": T.MUTED, "size": 11},
            )
        start = i * (width + _PANEL_GAP)
        axes[f"xaxis{suffix}"] = {
            "domain": [start, start + width],
            "anchor": "y",
            "range": _panel_range(values, median),
            "nticks": 6,
            "gridcolor": T.GRID,
            # On/off is a difference, so its zero is drawn.
            "zeroline": m.kind == "signed",
            "zerolinecolor": T.BASELINE,
            "tickfont": {"color": T.MUTED},
            "title": {"text": m.label, "font": {"color": T.MUTED, "size": 11}},
            "fixedrange": True,
            "automargin": True,
        }

    fig.update_layout(
        **_layout(
            height=_DRIVER_ROW_PX * len(ids) + 100,
            showlegend=False,
            margin={"l": 8, "r": 8, "t": 28, "b": 8},
            yaxis={
                "type": "category",
                "categoryorder": "array",
                "categoryarray": ids,
                "tickvals": ids,
                "ticktext": names,
                "tickfont": {"color": T.INK_2, "size": 11},
                "autorange": "reversed",
                "gridcolor": T.GRID,
                "fixedrange": True,
                "automargin": True,
                "ticksuffix": " ",
            },
            **axes,
        )
    )
    return fig


def _minutes_line(row: Any) -> str:
    """'2,261 min · 68 games for this team' for a hover."""
    minutes: Any = getattr(row, "minutes", None)
    games: Any = getattr(row, "games_played", None)
    parts = []
    if not diagnosis.missing(minutes):
        parts.append(f"{round(float(minutes)):,} min")
    if not diagnosis.missing(games):
        parts.append(f"{int(games)} games for this team")
    return " · ".join(parts)
