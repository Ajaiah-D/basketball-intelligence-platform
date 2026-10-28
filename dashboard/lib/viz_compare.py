"""Plotly charts for the Players page's Compare tab: a radar of percentiles
and a per-game stat line, two players in their own colours.

Both only show numbers. Neither marks a winner: no highlight on the larger
value, no shading of the larger shape. Kept apart from viz.py and
viz_diagnosis.py, which are already large, and built on viz._layout.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import NamedTuple

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from . import theme as T
from .viz import _empty, _layout

RADAR_HEIGHT = 440
# One stat's row in the bars: a label, a bar pair and room for the value.
_BAR_ROW_PX = 56
_BAR_LEGEND_PX = 44
# Headroom right of the longer bar so its printed value is never clipped.
_BAR_HEADROOM = 1.45


class RadarSide(NamedTuple):
    """One player on the radar: a percentile (0-100) on each axis, in the
    axes' order, and the text each point's hover prints."""

    name: str
    color: str
    values: Sequence[float]
    hovers: Sequence[str]


class BarStat(NamedTuple):
    """One stat of the per-game line: its label, each player's value
    (None when the stat doesn't exist for him) and the text printed for it,
    both in the sides' order."""

    label: str
    values: Sequence[float | None]
    texts: Sequence[str]


class BarSide(NamedTuple):
    """One player in the per-game line."""

    name: str
    color: str


def compare_radar(axes: Sequence[str], sides: Sequence[RadarSide]) -> go.Figure:
    """The sides' percentiles on one 0-100 polar chart, one spoke per axis
    (`axes` are the spoke names, in order). Each trace is a closed outline
    in the player's colour with a light tint inside, so two overlapping
    shapes stay readable; no side is drawn stronger than the other."""
    if len(axes) < 3 or not sides:
        return _empty("Not enough shared percentiles for a radar")
    fig = go.Figure()
    # The first spoke is repeated to close the outline.
    closed = [*axes, axes[0]]
    for i, side in enumerate(sides):
        values = [*side.values, side.values[0]]
        hovers = [*side.hovers, side.hovers[0]]
        fig.add_trace(
            go.Scatterpolar(
                r=values,
                theta=closed,
                name=side.name,
                legendgroup=str(i),
                mode="lines+markers",
                fill="toself",
                fillcolor=T.rgba(side.color, 0.18),
                line={"color": side.color, "width": 2.5},
                marker={"color": side.color, "size": 7},
                customdata=hovers,
                hovertemplate="%{theta}<br>%{customdata}<extra>" + side.name + "</extra>",
            )
        )
    fig.update_layout(
        **_layout(
            height=RADAR_HEIGHT,
            margin={"l": 76, "r": 76, "t": 64, "b": 24},
            polar={
                "bgcolor": "rgba(0,0,0,0)",
                # Stops short of the top so the top spoke's name clears the
                # legend, which wraps to two rows when the names are long.
                "domain": {"x": [0, 1], "y": [0, 0.82]},
                "radialaxis": {
                    "range": [0, 100],
                    "tickvals": [25, 50, 75],
                    "tickfont": {"color": T.MUTED, "size": 10},
                    "gridcolor": T.GRID,
                    "linecolor": T.GRID,
                    "angle": 90,
                    "tickangle": 90,
                },
                "angularaxis": {
                    "tickfont": {"color": T.INK_2, "size": 12},
                    "gridcolor": T.GRID,
                    "linecolor": T.BASELINE,
                    "direction": "clockwise",
                    "rotation": 90,
                },
            },
        )
    )
    return fig


def compare_bars(stats: Sequence[BarStat], sides: Sequence[BarSide]) -> go.Figure:
    """The per-game line, one row per stat with a bar for each player.

    Stats don't share a unit (points, steals, a percentage), so each row
    has its own scale: bars start at zero and are drawn against the larger
    of the two values, and the printed value is the number to read. A
    row's bars are in proportion to each other, but rows are not comparable
    to one another, and nothing marks the larger value."""
    if not stats or not sides:
        return _empty("No stats to compare")
    fig = make_subplots(
        rows=len(stats),
        cols=1,
        vertical_spacing=0.12 / max(len(stats) - 1, 1),
    )
    fig.update_layout(
        **_layout(
            height=_BAR_LEGEND_PX + _BAR_ROW_PX * len(stats),
            barmode="group",
            bargap=0.3,
            bargroupgap=0.08,
            # _layout's legend sits above the plot; the rows start below it.
            margin={"l": 8, "r": 8, "t": _BAR_LEGEND_PX, "b": 4},
        )
    )
    for row, stat in enumerate(stats, start=1):
        known = [v for v in stat.values if v is not None]
        top = max(known, default=0.0) or 1.0
        for i, side in enumerate(sides):
            value = stat.values[i]
            fig.add_trace(
                go.Bar(
                    x=[0.0 if value is None else value],
                    y=[stat.label],
                    orientation="h",
                    name=side.name,
                    legendgroup=str(i),
                    showlegend=row == 1,
                    marker={"color": side.color},
                    text=[stat.texts[i]],
                    textposition="outside",
                    cliponaxis=False,
                    textfont={"color": T.INK_2, "size": 12},
                    hovertemplate=stat.label
                    + ": "
                    + stat.texts[i]
                    + "<extra>"
                    + side.name
                    + "</extra>",
                ),
                row=row,
                col=1,
            )
        fig.update_xaxes(
            range=[0, top * _BAR_HEADROOM],
            visible=False,
            fixedrange=True,
            row=row,
            col=1,
        )
        fig.update_yaxes(
            tickfont={"color": T.INK_2, "size": 12},
            fixedrange=True,
            showline=False,
            showgrid=False,
            # The first side's bar on top, as the legend lists it.
            autorange="reversed",
            automargin=True,
            row=row,
            col=1,
        )
    return fig
