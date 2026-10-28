"""Plotly charts for the diagnosis views (the Teams page's league-ranks
profile, player breakdown and two-stat scatter, and the Players page's
game-by-game trend), in the house style of viz.py and built on its _layout.

Kept apart from viz.py, which is already ~1,000 lines.
"""

from __future__ import annotations

import textwrap
from collections.abc import Callable, Iterable, Mapping
from typing import Any, NamedTuple

import pandas as pd
import plotly.graph_objects as go

from core.fmt import matchup, ordinal

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


# --- The any-two-stats scatter -------------------------------------------------------

# Dot diameters: the picked team's is the larger, so it stands out in a
# crowd of 30 without a legend.
_SCATTER_DOT_PX = 10
_SCATTER_PICK_PX = 17


def lower_is_better(df: pd.DataFrame, col: str) -> bool:
    """Whether the league's #1 end of `col` is its low end, read off the
    `<col>_rank` column (rank 1 sits nearer the minimum than the maximum).
    The marts' ranks are the one place that knows which direction helps, so
    this asks them instead of keeping a list. False without ranks or values."""
    rank_col = f"{col}_rank"
    if col not in df.columns or rank_col not in df.columns:
        return False
    both = df[[col, rank_col]].dropna()
    if both.empty:
        return False
    top = float(both.loc[both[rank_col] == both[rank_col].min(), col].mean())
    low, high = float(both[col].min()), float(both[col].max())
    return abs(top - low) < abs(top - high)


def _default_fmt(key: str, value: float) -> str:
    return f"{value:.1f}"


def _standing(df: pd.DataFrame, col: str, i: int, pool: int) -> str:
    """' (#3 of 30)' for row i, or '' when the frame carries no rank. `pool`
    is how many rows the stat is ranked across."""
    rank_col = f"{col}_rank"
    if rank_col not in df.columns or diagnosis.missing(df[rank_col].iloc[i]):
        return ""
    return f" (#{int(df[rank_col].iloc[i])} of {pool})"


def _axis(label: str, reversed_: bool, vertical: bool) -> dict[str, Any]:
    """One scatter axis. A reversed axis says so in its title, since up (or
    right) then means a lower number."""
    side = "up" if vertical else "right"
    text = f"{label} (reversed: {side} = lower)" if reversed_ else label
    axis: dict[str, Any] = {
        "title": {"text": text, "font": {"color": T.MUTED, "size": 11}},
        "gridcolor": T.GRID,
        "tickfont": {"color": T.MUTED},
        "fixedrange": True,
        "automargin": True,
        "zeroline": False,
    }
    if reversed_:
        axis["autorange"] = "reversed"
    return axis


def _furthest(df: pd.DataFrame, x: str, y: str, count: int, skip: set[int]) -> set[int]:
    """Positions of the `count` points furthest from the average in
    standard-deviation units on both axes (leaving out `skip`): the ones
    worth a name."""
    zx = (df[x] - df[x].mean()) / (df[x].std(ddof=0) or 1.0)
    zy = (df[y] - df[y].mean()) / (df[y].std(ddof=0) or 1.0)
    dist = (zx**2 + zy**2).reset_index(drop=True).drop(index=list(skip))
    return set(dist.sort_values(ascending=False, kind="stable").index[: max(count, 0)])


def stat_scatter(
    df: pd.DataFrame,
    x: str,
    y: str,
    label_col: str,
    color_col: str,
    highlight: str | None = None,
    x_label: str | None = None,
    y_label: str | None = None,
    label_top: int = 12,
    invert: Iterable[str] = (),
    name_col: str | None = None,
    fmt: Callable[[str, float], str] | None = None,
    highlight_col: str | None = None,
    detail_col: str | None = None,
    highlight_color: str | None = None,
) -> go.Figure:
    """Any two columns of `df` against each other, a dot per row.

    Dots take the team colour of `color_col` (an abbreviation); the rows
    whose `highlight_col` (default `label_col`) equals `highlight` are drawn
    larger and outlined, on top. Dashed lines mark the average of each column, so position reads
    against the league instead of an arbitrary zero, and are the only
    labelled reference: no quadrant is named good or bad.

    `invert` lists the columns whose axis runs high to low, so up and right
    always lead to the better end; the axis title says so. `label_top`
    names that many dots (the picked ones always, however many they are,
    then the furthest from the averages while any of the count is left) so a
    crowd stays readable; the rest are unlabelled but still hover. A hover shows `name_col` (default `label_col`), both
    values through `fmt(column, value)` and, when `df` has `<column>_rank`,
    both ranks as "#3 of 30"; `detail_col`, when given, is a last hover line
    of ready-made text. `highlight_color`, when given, paints every highlighted
    dot that one colour instead of its own row's (a team's players, whichever
    team a traded one finished with). Rows missing either column are skipped."""
    fmt = fmt or _default_fmt
    # "of N" counts everything the stat was ranked across, so a team missing
    # the other stat does not shrink it (a rank column the mart left null
    # for a row is simply not in the pool).
    pools = {c: int(df[f"{c}_rank"].notna().sum()) for c in (x, y) if f"{c}_rank" in df.columns}
    data = df.dropna(subset=[x, y]).reset_index(drop=True)
    if data.empty:
        return _empty("No data for these stats this season")

    n = len(data)
    inverted = set(invert)
    names = data[name_col or label_col].tolist()
    labels = data[label_col].tolist()
    # The highlight can match a column other than the one that names the
    # dots (every player of one team, each labelled by name).
    matched = data[highlight_col or label_col].tolist()
    pick = [m == highlight for m in matched] if highlight is not None else [False] * n
    picked = {i for i in range(n) if pick[i]}
    # The picks are always named and count against the cap; more of them than
    # the cap leaves no room for the rest, but never loses a pick.
    named = picked | _furthest(data, x, y, label_top - len(picked), picked)

    hovers = [
        f"<b>{names[i]}</b><br>{x_label or x} {fmt(x, float(data[x][i]))}"
        f"{_standing(data, x, i, pools.get(x, 0))}<br>{y_label or y} {fmt(y, float(data[y][i]))}"
        f"{_standing(data, y, i, pools.get(y, 0))}"
        f"{'<br>' + str(data[detail_col][i]) if detail_col else ''}"
        for i in range(n)
    ]
    colors = [
        highlight_color if highlight_color and pick[i] else T.team_color(str(c))
        for i, c in enumerate(data[color_col])
    ]

    def trace(rows: list[int], is_pick: bool) -> go.Scatter:
        return go.Scatter(
            x=[data[x][i] for i in rows],
            y=[data[y][i] for i in rows],
            mode="markers+text",
            text=[str(labels[i]) if i in named else "" for i in rows],
            textposition="top center",
            textfont={"color": T.INK if is_pick else T.INK_2, "size": 11 if is_pick else 9},
            marker={
                "size": _SCATTER_PICK_PX if is_pick else _SCATTER_DOT_PX,
                "color": [colors[i] for i in rows],
                # The pick's ring is the page's ink; the others' a page-coloured
                # gap that keeps overlapping dots apart.
                "line": {"color": T.INK if is_pick else T.PAGE, "width": 2.5 if is_pick else 1.5},
            },
            hovertext=[hovers[i] for i in rows],
            hovertemplate="%{hovertext}<extra></extra>",
            cliponaxis=False,
            showlegend=False,
        )

    fig = go.Figure()
    fig.add_trace(trace([i for i in range(n) if not pick[i]], False))
    if any(pick):
        fig.add_trace(trace([i for i in range(n) if pick[i]], True))
    fig.add_vline(
        x=float(data[x].mean()), line_color=T.MUTED, line_width=1, line_dash="dash", layer="below"
    )
    fig.add_hline(
        y=float(data[y].mean()), line_color=T.MUTED, line_width=1, line_dash="dash", layer="below"
    )
    fig.add_annotation(
        x=float(data[x].mean()),
        y=1,
        xref="x",
        yref="paper",
        yanchor="bottom",
        text="league average",
        showarrow=False,
        font={"color": T.MUTED, "size": 11},
    )
    fig.update_layout(
        **_layout(
            showlegend=False,
            margin={"l": 8, "r": 8, "t": 24, "b": 8},
            xaxis=_axis(x_label or x, x in inverted, vertical=False),
            yaxis=_axis(y_label or y, y in inverted, vertical=True),
        )
    )
    return fig


# --- The Players page's game-by-game trend ----------------------------------------


class GameStat(NamedTuple):
    """A stat the game log and trend show: its column in
    data.players.player_games, its name in the chart title, its printed
    decimals, and the weight a run of games averages it over (None: each
    game counts once)."""

    col: str
    name: str
    decimals: int = 0
    weight: str | None = None


# In the picker's order. True shooting averages over shot volume, so a
# 1-for-1 night doesn't count the same as a 10-for-25 one.
GAME_STATS: dict[str, GameStat] = {
    "PTS": GameStat("pts", "Points"),
    "REB": GameStat("reb", "Rebounds"),
    "AST": GameStat("ast", "Assists"),
    "3PM": GameStat("tpm", "Threes made"),
    "TS%": GameStat("ts_pct", "True shooting %", decimals=1, weight="shot_poss"),
    "+/-": GameStat("plus_minus", "Plus-minus"),
}
TREND_WINDOW = 5


def _rolling(games: pd.DataFrame, stat: GameStat, window: int) -> pd.Series:
    """The `window`-game average at each game, NaN until there are that many
    games behind it."""
    values = games[stat.col].astype(float)
    if stat.weight is None:
        return values.rolling(window, min_periods=window).mean()
    # A game with no value (no shots) adds no weight, rather than a zero.
    weight = games[stat.weight].astype(float).where(values.notna(), 0.0).fillna(0.0)
    total = (values.fillna(0.0) * weight).rolling(window, min_periods=window).sum()
    shots = weight.rolling(window, min_periods=window).sum()
    return total / shots.where(shots > 0)


def stat_trend(games: pd.DataFrame, stat: str, season_avg: float) -> go.Figure:
    """One stat game by game (a neutral bar per game), its 5-game rolling
    average (the accent line) and a dashed line at `season_avg`, his season
    figure from mart_player_season. `games` is data.players.player_games,
    oldest first; `stat` is a GAME_STATS key, named in the title.

    The rolling line only starts once there are five games behind it: from
    the first game it would be one game's value wearing a "5-game average"
    label, an early swing that never happened. A game without the stat (TS%
    with no shots) has no bar and doesn't pull the line toward zero."""
    if games.empty:
        return _empty("No games this season")
    spec = GAME_STATS[stat]
    window = min(TREND_WINDOW, len(games))
    dates = games["game_date"]
    roll = _rolling(games, spec, window)
    value_fmt = f":.{spec.decimals}f"

    fig = go.Figure()
    fig.add_bar(
        x=dates,
        y=games[spec.col].astype(float),
        name="Game",
        marker={"color": T.BASELINE},
        customdata=[
            matchup(away, opp) for away, opp in zip(games["is_away"], games["opp"], strict=True)
        ],
        hovertemplate=f"%{{customdata}}: %{{y{value_fmt}}} {stat}<extra></extra>",
    )
    fig.add_scatter(
        x=dates,
        y=roll,
        name=f"{window}-game avg",
        mode="lines",
        line={"color": T.ACCENT, "width": 2},
        connectgaps=False,
        hovertemplate=f"{window}-game avg: %{{y:.1f}}<extra></extra>",
    )
    # His own season figure turns the rolling line into a story: where he
    # ran hot or cold against his year.
    if season_avg == season_avg:
        fig.add_hline(y=season_avg, line_color=T.MUTED, line_width=1, line_dash="dash")
        # Named in the legend: a label on the line itself sits under the bars
        # and the rolling line wherever it goes. The trace has no points, so
        # it only draws the legend entry.
        fig.add_scatter(
            x=[None],
            y=[None],
            name=f"season avg {season_avg:.1f}",
            mode="lines",
            line={"color": T.MUTED, "width": 1, "dash": "dash"},
            hoverinfo="skip",
        )
    if roll.notna().any():
        last = roll.last_valid_index()
        fig.add_annotation(
            x=dates[last].to_pydatetime(),
            y=float(roll[last]),
            text=f"{roll[last]:.1f}",
            showarrow=False,
            xshift=22,
            font={"color": T.ACCENT, "size": 12},
        )
    fig.update_layout(
        **_layout(
            # The title on its own line at the top, the legend (the house
            # one, left-aligned) under it: side by side they collide at
            # phone width.
            title={
                "text": f"{spec.name} by game",
                "x": 0,
                "xanchor": "left",
                "y": 1,
                "yref": "container",
                "yanchor": "top",
                "pad": {"t": 6},
                "font": {"size": 13, "color": T.INK},
            },
            margin={"l": 8, "r": 8, "t": 70, "b": 8},
            # Narrow keys and a smaller font keep the three entries on one
            # row at phone width.
            legend={
                "orientation": "h",
                "yanchor": "bottom",
                "y": 1.02,
                "x": 0,
                "itemwidth": 30,
                "font": {"color": T.INK_2, "size": 11},
            },
            hovermode="x unified",
            bargap=0.45,
        )
    )
    return fig
