"""Plotly chart constructors, styled to the app theme.

House chart rules: one axis per chart, 2px lines, recessive hairline grid,
categorical hues in fixed slot order, emphasis = accent + de-emphasis gray,
diverging = blue/red around a zero baseline, hover tooltips on every mark.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from . import theme as T

PLOTLY_CONFIG = {"displayModeBar": False}


def _layout(**overrides) -> dict:
    base = dict(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=T.FONT, color=T.INK_2, size=12),
        margin=dict(l=8, r=8, t=28, b=8),
        # the modebar is hidden, so a drag/pinch zoom would be unrecoverable -
        # every chart is a fixed view (overriding axes must keep fixedrange)
        dragmode=False,
        # automargin lets plotly reserve room for tick labels and titles. The
        # explicit margin above otherwise wins and clips them: without this a
        # y axis reading 10..50 renders as a column of "0"s. Any chart that
        # replaces these axis dicts wholesale has to set it again.
        xaxis=dict(gridcolor=T.GRID, zerolinecolor=T.BASELINE, linecolor=T.BASELINE,
                   tickfont=dict(color=T.MUTED), fixedrange=True, automargin=True),
        yaxis=dict(gridcolor=T.GRID, zerolinecolor=T.BASELINE, linecolor=T.BASELINE,
                   tickfont=dict(color=T.MUTED), fixedrange=True, automargin=True),
        hoverlabel=dict(bgcolor=T.SURFACE, bordercolor=T.BORDER,
                        font=dict(family=T.FONT, color=T.INK)),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0,
                    font=dict(color=T.INK_2)),
        height=320,
    )
    base.update(overrides)
    return base


def player_trend(games: pd.DataFrame) -> go.Figure:
    """Points per game (context bars) + 5-game rolling average (emphasis line),
    against the season average as a reference.

    The rolling line only starts once there are five games behind it. With
    min_periods=1 the first point was just that game's score wearing a
    "5-game average" label, which reads as a wild early swing that never
    actually happened."""
    df = games.copy()
    window = min(5, len(df))
    df["roll"] = df["points"].rolling(window, min_periods=window).mean()
    season_avg = df["points"].mean()

    fig = go.Figure()
    fig.add_bar(
        x=df["game_date"], y=df["points"], name="Points",
        marker=dict(color=T.BASELINE),
        hovertemplate="%{x|%b %d} vs %{customdata}<br>%{y} pts<extra></extra>",
        customdata=df["matchup"].str[-3:],
    )
    # A flat season average turns the rolling line into a story: this is
    # where the player was running hot or cold relative to their own year.
    fig.add_hline(y=season_avg, line_color=T.MUTED, line_width=1, line_dash="dot")
    # Annotation x values go through a stricter serializer than the traces
    # do, and a pandas Timestamp is not JSON serializable there.
    fig.add_annotation(
        x=df["game_date"].iloc[0].to_pydatetime(), y=season_avg,
        text=f"season avg {season_avg:.1f}",
        showarrow=False, yshift=10, xanchor="left",
        font=dict(color=T.MUTED, size=10),
    )
    fig.add_scatter(
        x=df["game_date"], y=df["roll"], name=f"{window}-game avg",
        mode="lines", line=dict(color=T.ACCENT, width=2),
        connectgaps=False,
        hovertemplate=f"{window}-game avg: %{{y:.1f}}<extra></extra>",
    )
    if df["roll"].notna().any():
        last = df.dropna(subset=["roll"]).iloc[-1]
        fig.add_annotation(x=last["game_date"].to_pydatetime(), y=last["roll"],
                           text=f"{last['roll']:.1f}",
                           showarrow=False, xshift=22, font=dict(color=T.ACCENT, size=12))
    fig.update_layout(**_layout(hovermode="x unified", bargap=0.45))
    return fig


def career_trend(seasons_df: pd.DataFrame, stat: str, label: str,
                 weight: str = "gp", as_rate: bool = False) -> go.Figure:
    """Per-season values (context bars) + weighted career average to date
    (emphasis line). seasons_df comes from db.player_season_breakdown.

    `weight` is what the running average is weighted by. Games played is
    right for per-game stats; a percentage like TS% has to be weighted by
    the attempts behind it, or a 20-game season counts the same as an
    80-game one. Seasons where the stat is missing (the source has no field
    goal attempts before 1985-86) are dropped rather than shown as zero,
    which would draw a career-long collapse that never happened.

    `as_rate` switches the season values from bars to dots. A percentage
    lives in a narrow band (a career of true shooting might run 51 to 64),
    and a bar has to start at zero or it misstates the magnitude, which
    leaves the whole story squeezed into the top of the panel. Dots carry no
    length to misread, so the axis can close in on the range instead."""
    df = seasons_df.copy()
    df = df[df[stat].notna()]
    if df.empty:
        return _empty(f"No {label} data for these seasons")
    w = df[weight] if weight in df else df["gp"]
    df["cum"] = (df[stat] * w).cumsum() / w.cumsum()
    fig = go.Figure()
    hover = ("%{x} (%{customdata[0]}, %{customdata[1]} GP)<br>"
             "%{y:.1f} " + label + "<extra></extra>")
    if as_rate:
        fig.add_scatter(
            x=df["season"], y=df[stat], name=label, mode="markers",
            marker=dict(color=T.BASELINE, size=10,
                        line=dict(color=T.SURFACE, width=2)),
            customdata=df[["team", "gp"]], hovertemplate=hover,
        )
    else:
        fig.add_bar(
            x=df["season"], y=df[stat], name=label,
            marker=dict(color=T.BASELINE),
            customdata=df[["team", "gp"]], hovertemplate=hover,
        )
    fig.add_scatter(
        x=df["season"], y=df["cum"], name="Career avg to date",
        mode="lines", line=dict(color=T.ACCENT, width=2),
        hovertemplate="Career avg: %{y:.1f}<extra></extra>",
    )
    last = df.iloc[-1]
    fig.add_annotation(x=last["season"], y=last["cum"], text=f"{last['cum']:.1f}",
                       showarrow=False, xshift=26, font=dict(color=T.ACCENT, size=12))
    layout = dict(
        hovermode="x unified", bargap=0.45,
        # season labels like "1984-85" parse as dates unless forced categorical
        xaxis=dict(type="category", gridcolor=T.GRID, linecolor=T.BASELINE,
                   tickfont=dict(color=T.MUTED), fixedrange=True, automargin=True,
                   tickangle=-45 if len(df) > 14 else 0),
    )
    if as_rate:
        lo = min(df[stat].min(), df["cum"].min())
        hi = max(df[stat].max(), df["cum"].max())
        pad = max(2.0, (hi - lo) * 0.25)
        layout["yaxis"] = dict(range=[lo - pad, hi + pad], gridcolor=T.GRID,
                               tickfont=dict(color=T.MUTED), fixedrange=True,
                               automargin=True, ticksuffix="%")
    fig.update_layout(**_layout(**layout))
    return fig


def shooting_profile(player_row: pd.Series, league: pd.Series, player_name: str) -> go.Figure:
    """Player shooting percentages vs league average - emphasis form.
    Player labels carry attempt volume so a hot % on tiny volume is
    visibly flagged rather than looking elite."""
    cats = ["FG%", "3P%", "FT%"]
    pvals = [player_row["fg_pct"], player_row["fg3_pct"], player_row["ft_pct"]]
    attempts = [player_row.get("fga_pg"), player_row.get("tpa_pg"), player_row.get("fta_pg")]
    lvals = [league["fg_pct"], league["fg3_pct"], league["ft_pct"]]

    def label(v, att):
        if pd.isna(v):
            return "-"
        return f"{v:.1f} on {att:.1f}/g" if pd.notna(att) else f"{v:.1f}"

    fig = go.Figure()
    fig.add_bar(y=cats, x=lvals, orientation="h", name="League",
                marker=dict(color=T.BASELINE),
                text=[f"{v:.0f}" if pd.notna(v) else "-" for v in lvals],
                textposition="outside",
                textfont=dict(color=T.MUTED),
                hovertemplate="League %{y}: %{x:.1f}<extra></extra>")
    fig.add_bar(y=cats, x=pvals, orientation="h", name=player_name,
                marker=dict(color=T.ACCENT),
                text=[label(v, a) for v, a in zip(pvals, attempts)],
                textposition="outside", textfont=dict(color=T.INK),
                customdata=attempts,
                hovertemplate="%{y}: %{x:.1f} on %{customdata:.1f} attempts/game<extra></extra>")
    # Outside labels need room past the longest bar or they get clipped: a
    # 90% free throw shooter would otherwise have its label run off a 0-100
    # axis. Headroom scales with the values actually plotted.
    top = max([v for v in pvals + lvals if pd.notna(v)], default=100)
    fig.update_layout(**_layout(barmode="group", bargap=0.35,
                                height=260,
                                xaxis=dict(range=[0, top * 1.55], gridcolor=T.GRID,
                                           tickfont=dict(color=T.MUTED),
                                           tickvals=[0, 25, 50, 75, 100],
                                           fixedrange=True, automargin=True),
                                yaxis=dict(tickfont=dict(color=T.INK_2),
                                           fixedrange=True, automargin=True)))
    return fig


def team_margins(games: pd.DataFrame) -> go.Figure:
    """Per-game scoring margin, diverging around zero (blue win / red loss)."""
    df = games.copy()
    df["margin"] = df["points"] - df["opp_points"]
    colors = [T.DIVERGE_POS if m > 0 else T.DIVERGE_NEG for m in df["margin"]]
    fig = go.Figure()
    fig.add_bar(
        x=df["game_date"], y=df["margin"],
        marker=dict(color=colors),
        customdata=df[["opponent", "points", "opp_points"]],
        hovertemplate=("%{x|%b %d} vs %{customdata[0]}<br>"
                       "%{customdata[1]}-%{customdata[2]} (%{y:+})<extra></extra>"),
    )
    fig.add_hline(y=0, line_color=T.BASELINE, line_width=1)
    fig.update_layout(**_layout(bargap=0.35, showlegend=False))
    return fig


def game_worm(pbp: pd.DataFrame, home: str, away: str) -> go.Figure:
    """Game flow: score margin (home - away) over game time. Diverging fill."""
    df = pbp.copy()
    clk = df["game_clock"].str.extract(r"PT(\d+)M([\d.]+)S")
    remaining = clk[0].astype(float) * 60 + clk[1].astype(float)
    # Elapsed = seconds in completed periods (12-min quarters, 5-min OTs)
    # plus time used in the current period.
    period = df["period"]
    prior_secs = ((period.clip(upper=4) - 1) * 720).where(
        period <= 4, 2880 + (period - 5) * 300)
    period_len = period.map(lambda p: 720 if p <= 4 else 300)
    df["elapsed_min"] = (prior_secs + (period_len - remaining)) / 60

    df = df.dropna(subset=["elapsed_min"]).copy()
    df["margin"] = (df["score_home"] - df["score_away"]).ffill().fillna(0)
    df = df.drop_duplicates(subset="elapsed_min", keep="last")

    fig = go.Figure()
    fig.add_scatter(
        x=df["elapsed_min"], y=df["margin"].clip(lower=0), name=f"{home} lead",
        mode="lines", line=dict(width=0), fill="tozeroy",
        fillcolor="rgba(57,135,229,0.45)", hoverinfo="skip",
    )
    fig.add_scatter(
        x=df["elapsed_min"], y=df["margin"].clip(upper=0), name=f"{away} lead",
        mode="lines", line=dict(width=0), fill="tozeroy",
        fillcolor="rgba(230,103,103,0.45)", hoverinfo="skip",
    )
    fig.add_scatter(
        x=df["elapsed_min"], y=df["margin"], name="Margin",
        mode="lines", line=dict(color=T.INK_2, width=2), showlegend=False,
        customdata=df[["score_home", "score_away"]],
        hovertemplate=("Q%{text} · %{x:.0f} min<br>"
                       f"{home} %{{customdata[0]}} - {away} %{{customdata[1]}}"
                       "<extra></extra>"),
        text=df["period"],
    )
    for qend in (12, 24, 36, 48):
        if df["elapsed_min"].max() >= qend - 1:
            fig.add_vline(x=qend, line_color=T.GRID, line_width=1)
    fig.add_hline(y=0, line_color=T.BASELINE, line_width=1)
    fig.update_layout(**_layout(
        hovermode="x unified", height=300,
        xaxis=dict(title=dict(text="Game time (min)", font=dict(color=T.MUTED)),
                   gridcolor="rgba(0,0,0,0)", zerolinecolor=T.BASELINE,
                   tickfont=dict(color=T.MUTED), fixedrange=True, automargin=True),
        yaxis=dict(title=dict(text=f"← {away}   margin   {home} →",
                              font=dict(color=T.MUTED)),
                   gridcolor=T.GRID, tickfont=dict(color=T.MUTED), fixedrange=True,
                   automargin=True),
    ))
    return fig


def _court_shapes() -> list[dict]:
    """Half-court in PBP legacy coordinates: tenths of feet, hoop at (0,0),
    baseline at y=-47.5, halfcourt at y=422.5."""
    line = dict(color=T.BASELINE, width=1.5)
    shapes = [
        # boundary
        dict(type="rect", x0=-250, y0=-47.5, x1=250, y1=422.5, line=line),
        # paint (outer and inner)
        dict(type="rect", x0=-80, y0=-47.5, x1=80, y1=142.5, line=line),
        dict(type="rect", x0=-60, y0=-47.5, x1=60, y1=142.5, line=line),
        # backboard + hoop
        dict(type="line", x0=-30, y0=-7.5, x1=30, y1=-7.5,
             line=dict(color=T.INK_2, width=2)),
        dict(type="circle", x0=-7.5, y0=-7.5, x1=7.5, y1=7.5,
             line=dict(color=T.INK_2, width=1.5)),
        # free-throw circle
        dict(type="circle", x0=-60, y0=82.5, x1=60, y1=202.5, line=line),
        # restricted area arc
        dict(type="path",
             path="M -40 0 C -40 22, -22 40, 0 40 C 22 40, 40 22, 40 0", line=line),
        # 3pt: corner lines + arc (r=237.5, corners at x=+/-220, y<=89.5)
        dict(type="line", x0=-220, y0=-47.5, x1=-220, y1=89.5, line=line),
        dict(type="line", x0=220, y0=-47.5, x1=220, y1=89.5, line=line),
        dict(type="path",
             path="M -220 89.5 C -135 235, 135 235, 220 89.5", line=line),
        # center circle
        dict(type="path",
             path="M -60 422.5 C -60 389, -33 362.5, 0 362.5 "
                  "C 33 362.5, 60 389, 60 422.5", line=line),
    ]
    return shapes


def shot_chart(pbp: pd.DataFrame, home: str, away: str) -> go.Figure:
    """All field-goal attempts for one game on a half court, colored by
    team (team identity colors); made = filled dot, missed = open cross."""
    shots = pbp[pbp["is_field_goal"] & pbp["shot_x"].notna()].copy()
    shots["shot_y"] = shots["shot_y"].clip(upper=420)
    fig = go.Figure()
    for team in (away, home):
        color = T.TEAM_COLORS.get(team, T.ACCENT)
        tshots = shots[shots["team_tricode"] == team]
        for result, symbol, filled in (("Made", "circle", True),
                                       ("Missed", "x-thin", False)):
            sub = tshots[tshots["shot_result"] == result]
            fig.add_scatter(
                x=sub["shot_x"], y=sub["shot_y"], mode="markers",
                name=f"{team} {result.lower()}",
                marker=dict(
                    symbol=symbol, size=9 if filled else 8,
                    color=color if filled else "rgba(0,0,0,0)",
                    line=dict(color=color, width=1.5),
                    opacity=0.9 if filled else 0.5,
                ),
                customdata=sub[["player_name", "shot_distance_ft", "period"]],
                hovertemplate=("%{customdata[0]} - %{customdata[1]} ft (Q%{customdata[2]})"
                               "<extra>" + f"{team} {result.lower()}" + "</extra>"),
            )
    fig.update_layout(**_layout(
        height=520, shapes=_court_shapes(),
        xaxis=dict(range=[-260, 260], visible=False, fixedrange=True),
        yaxis=dict(range=[-60, 440], visible=False, fixedrange=True,
                   scaleanchor="x", scaleratio=1),
        legend=dict(orientation="h", yanchor="top", y=-0.02, x=0.5, xanchor="center",
                    font=dict(color=T.INK_2)),
        margin=dict(l=8, r=8, t=8, b=8),
    ))
    return fig


def rating_quadrant(teams: pd.DataFrame, highlight: str | None = None) -> go.Figure:
    """Offence against defence, every team in one view. Defensive rating is
    inverted so that up and right is always better and the four quadrants
    read without a legend. Emphasis form: the selected team takes the accent,
    everyone else recedes to the baseline gray."""
    df = teams.dropna(subset=["offensive_rating", "defensive_rating"]).copy()
    if df.empty:
        return _empty("No efficiency data for this season")

    x_mid = df["offensive_rating"].mean()
    y_mid = df["defensive_rating"].mean()
    is_pick = df["team_abbreviation"] == highlight
    colors = [T.ACCENT if p else T.BASELINE for p in is_pick]
    sizes = [15 if p else 10 for p in is_pick]

    fig = go.Figure()
    # Quadrant dividers sit at the league average, so position is read
    # relative to the league rather than to an arbitrary zero. They use the
    # baseline colour, not the grid colour, or they are indistinguishable
    # from ordinary gridlines and the quadrants stop reading as quadrants.
    fig.add_vline(x=x_mid, line_color=T.BASELINE, line_width=1)
    fig.add_hline(y=y_mid, line_color=T.BASELINE, line_width=1)
    fig.add_annotation(x=x_mid, y=df["defensive_rating"].min(), text="league average",
                       showarrow=False, yshift=10, xshift=42,
                       font=dict(color=T.MUTED, size=10))
    fig.add_scatter(
        x=df["offensive_rating"], y=df["defensive_rating"],
        mode="markers+text",
        text=df["team_abbreviation"],
        textposition="top center",
        textfont=dict(color=T.INK_2, size=9),
        marker=dict(color=colors, size=sizes,
                    line=dict(color=T.SURFACE, width=2)),  # 2px surface ring
        customdata=df[["team_name", "net_rating", "pace"]],
        hovertemplate=("%{customdata[0]}<br>Offence %{x:.1f} · Defence %{y:.1f}"
                       "<br>Net %{customdata[1]:+.1f} · Pace %{customdata[2]:.1f}"
                       "<extra></extra>"),
        showlegend=False,
    )
    fig.update_layout(**_layout(
        height=420,
        xaxis=dict(title=dict(text="Offensive rating (points scored per 100)",
                              font=dict(color=T.MUTED)),
                   gridcolor=T.GRID, tickfont=dict(color=T.MUTED), fixedrange=True,
                   automargin=True),
        # Reversed so better defence (fewer points allowed) is higher up
        yaxis=dict(title=dict(text="Defensive rating (points allowed per 100)",
                              font=dict(color=T.MUTED)),
                   autorange="reversed",
                   gridcolor=T.GRID, tickfont=dict(color=T.MUTED), fixedrange=True,
                   automargin=True),
    ))
    return fig


def percentile_bars(rows: list[tuple[str, float, float]]) -> go.Figure:
    """Where a player ranks among qualified peers, one row per metric.
    Each bar is a percentile (0-100), so metrics on different scales share
    one axis honestly. The raw value rides along as the label, because a
    percentile alone hides whether 90th means 38% or 44%."""
    if not rows:
        return _empty("Not enough qualified players to rank against")
    labels = [r[0] for r in rows]
    pcts = [r[1] for r in rows]
    raws = [r[2] for r in rows]

    fig = go.Figure()
    fig.add_bar(
        y=labels, x=pcts, orientation="h",
        marker=dict(color=T.ACCENT, cornerradius=4),
        text=[f"{v:.1f}  ({p:.0f}th)" for v, p in zip(raws, pcts)],
        textposition="outside", textfont=dict(color=T.INK_2, size=11),
        hovertemplate="%{y}: %{customdata:.1f}, better than %{x:.0f}% of qualified players<extra></extra>",
        customdata=raws,
        showlegend=False,
    )
    fig.add_vline(x=50, line_color=T.BASELINE, line_width=1)
    fig.update_layout(**_layout(
        height=max(200, 42 * len(rows)), bargap=0.35,
        # Headroom past 100 so the outside labels are never clipped
        xaxis=dict(range=[0, 148], gridcolor=T.GRID, tickfont=dict(color=T.MUTED),
                   fixedrange=True, tickvals=[0, 25, 50, 75, 100],
                   title=dict(text="Percentile among qualified players",
                              font=dict(color=T.MUTED)), automargin=True),
        yaxis=dict(tickfont=dict(color=T.INK_2), fixedrange=True,
                   autorange="reversed", automargin=True),
    ))
    return fig


def compare_dumbbell(metrics: list[str], a_vals: list[float], b_vals: list[float],
                     a_name: str, b_name: str) -> go.Figure:
    """Two players across the same metrics, as percentiles so one axis works
    for all of them. The connecting line makes the gap the thing you read
    first, which a pair of bars does not."""
    if not metrics:
        return _empty("No shared metrics to compare")
    fig = go.Figure()
    for m, a, b in zip(metrics, a_vals, b_vals):
        fig.add_scatter(
            x=[a, b], y=[m, m], mode="lines",
            line=dict(color=T.BASELINE, width=2),
            hoverinfo="skip", showlegend=False,
        )
    for vals, name, color in ((a_vals, a_name, T.SERIES[0]),
                              (b_vals, b_name, T.SERIES[1])):
        fig.add_scatter(
            x=vals, y=metrics, mode="markers", name=name,
            marker=dict(color=color, size=12,
                        line=dict(color=T.SURFACE, width=2)),
            hovertemplate="%{y}: %{x:.0f}th percentile<extra>" + name + "</extra>",
        )
    # Median marker uses the baseline colour so it separates from the
    # ordinary gridlines at 25 and 75.
    fig.add_vline(x=50, line_color=T.BASELINE, line_width=1)
    fig.update_layout(**_layout(
        height=max(240, 46 * len(metrics)),
        xaxis=dict(range=[0, 100], gridcolor=T.GRID, tickfont=dict(color=T.MUTED),
                   fixedrange=True, tickvals=[0, 25, 50, 75, 100],
                   title=dict(text="Percentile among qualified players",
                              font=dict(color=T.MUTED)), automargin=True),
        yaxis=dict(tickfont=dict(color=T.INK_2), fixedrange=True,
                   autorange="reversed", automargin=True),
    ))
    return fig


def _empty(message: str) -> go.Figure:
    """Placeholder so a view with no data renders a sentence instead of an
    empty axis box."""
    fig = go.Figure()
    fig.add_annotation(text=message, showarrow=False,
                       font=dict(color=T.MUTED, size=13),
                       xref="paper", yref="paper", x=0.5, y=0.5)
    fig.update_layout(**_layout(
        height=200,
        xaxis=dict(visible=False, fixedrange=True),
        yaxis=dict(visible=False, fixedrange=True),
    ))
    return fig


def quick_chart(df: pd.DataFrame, kind: str, x: str, y: str,
                color: str | None = None) -> go.Figure:
    """Dev Lab chart builder. Categorical hues follow slot order."""
    fig = go.Figure()
    groups = [(None, df)] if not color else list(df.groupby(color, sort=True))
    if color and len(groups) > 8:
        raise ValueError(f"'{color}' has {len(groups)} distinct values - max 8 series. "
                         "Aggregate or filter first.")
    for i, (name, g) in enumerate(groups):
        c = T.SERIES[i % len(T.SERIES)] if color else T.ACCENT
        label = str(name) if name is not None else y
        if kind == "bar":
            fig.add_bar(x=g[x], y=g[y], name=label, marker=dict(color=c))
        elif kind == "line":
            fig.add_scatter(x=g[x], y=g[y], name=label, mode="lines",
                            line=dict(color=c, width=2))
        elif kind == "area":
            fig.add_scatter(x=g[x], y=g[y], name=label, mode="lines",
                            line=dict(color=c, width=2), fill="tozeroy")
        else:  # scatter
            fig.add_scatter(x=g[x], y=g[y], name=label, mode="markers",
                            marker=dict(color=c, size=9))
    fig.update_layout(**_layout(height=420, showlegend=bool(color),
                                bargap=0.3 if kind == "bar" else 0))
    fig.update_xaxes(title=dict(text=x, font=dict(color=T.MUTED)), automargin=True)
    fig.update_yaxes(title=dict(text=y, font=dict(color=T.MUTED)), automargin=True)
    return fig
