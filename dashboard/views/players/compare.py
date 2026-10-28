"""The Players page's Compare tab: two player-seasons head to head, from any
era. A radar of eight percentiles (each player ranked among the qualified
players of his own season, so a 1996 season and a 2026 season sit on the
same footing) and the per-game line side by side.

The tab shows numbers and never calls a winner. Each side is a name search
plus a pick of that name's player-seasons; with the search empty the pick is
the sidebar season's top scorers, and the tab opens on the top two.
"""

import html
from typing import NamedTuple

import pandas as pd
import streamlit as st

from core.fmt import ordinal
from dashboard.lib import glossary, viz, viz_compare
from dashboard.lib import state as shared_state
from dashboard.lib import theme as T
from dashboard.lib.data import diagnosis, players, seasons
from dashboard.views.players.scatter import METRICS, format_value

A_KEY = "players_compare_a"
B_KEY = "players_compare_b"
A_SEARCH_KEY = "players_compare_a_search"
B_SEARCH_KEY = "players_compare_b_search"

# The picks offered with no search: this many of the season's top scorers.
TOP_SCORERS = 20
# A search lists at most this many player-seasons, newest first.
MAX_MATCHES = 60
# Fewer spokes than this is a line or a wedge, not a shape to compare.
MIN_SPOKES = 3

NOT_QUALIFIED = "not enough games for percentiles"
METHOD = (
    "Percentiles rank each player among the qualified players of his own season, "
    "so players from different eras compare on the same footing."
)


class RadarAxis(NamedTuple):
    """One spoke: its plain name, the mart column holding the stat it ranks
    (its percentile is `<column>_pctile`) and the stat's label and glossary
    term."""

    name: str
    column: str
    label: str
    term: str


# In the radar's order, clockwise from the top.
RADAR_AXES = (
    RadarAxis("Scoring", "points_per_game", "PTS", "PTS"),
    RadarAxis("Efficiency", "true_shooting_pct", "TS%", "TS%"),
    RadarAxis("Rebounding", "rebound_pct", "REB%", "REB%"),
    RadarAxis("Playmaking", "assist_pct", "AST%", "AST%"),
    RadarAxis("Ball security", "turnover_pct", "TOV%", "TOV%"),
    RadarAxis("Steals", "steal_pct", "STL%", "STL%"),
    RadarAxis("Blocks", "block_pct", "BLK%", "BLK%"),
    RadarAxis("3-pt volume", "threes_made_per_game", "3PM", "3PM"),
)

# The per-game line: label and column (all keys of scatter.METRICS, which
# gives each one's glossary term and print format).
STAT_LINE = (
    ("PTS", "points_per_game"),
    ("REB", "rebounds_per_game"),
    ("AST", "assists_per_game"),
    ("STL", "steals_per_game"),
    ("BLK", "blocks_per_game"),
    ("3PM", "threes_made_per_game"),
    ("TS%", "true_shooting_pct"),
    ("MIN", "minutes_per_game"),
)


def pick_id(season: str, player_id: int) -> str:
    """The pick box's value for one player-season."""
    return f"{season}|{int(player_id)}"


def parse_pick(pick: str) -> tuple[str, int]:
    """(season, player_id) from a pick_id."""
    season, player_id = pick.split("|")
    return season, int(player_id)


def available_axes(rows: list[pd.Series]) -> tuple[list[RadarAxis], dict[str, list[str]]]:
    """The spokes every one of `rows` has a percentile for, and the names of
    those it lacks by season ({"1984-85": ["Rebounding", ...]}). A spoke
    either side lacks is dropped for both, so the two outlines are drawn on
    the same axes."""
    kept = [axis for axis in RADAR_AXES if all(pd.notna(r[f"{axis.column}_pctile"]) for r in rows)]
    dropped: dict[str, list[str]] = {}
    for row in rows:
        for axis in RADAR_AXES:
            if pd.isna(row[f"{axis.column}_pctile"]):
                names = dropped.setdefault(row["season"], [])
                if axis.name not in names:
                    names.append(axis.name)
    return kept, dropped


def side_colors(a_team: str, b_team: str) -> tuple[str, str]:
    """Each side's team colour; the second takes the accent when the two
    match (two teams of one colour, or the same player on both sides)."""
    first, second = T.team_color(a_team), T.team_color(b_team)
    if second == first:
        second = T.ACCENT if first != T.ACCENT else T.SERIES[1]
    return first, second


def _label(row: pd.Series) -> str:
    return f"{row['player']} · {row['season']} · {row['team_label']}"


def _picker(side: str, key: str, search_key: str, sidebar_season: str) -> tuple[str, int] | None:
    """One side: the search box and the pick of matching player-seasons.
    Returns (season, player_id), or None when nothing matches the search."""
    search = st.text_input(
        f"Player {side}",
        key=search_key,
        placeholder="Search any player",
        help="Leave blank to pick from the season's top scorers",
    ).strip()
    rows = (
        players.player_seasons_matching(search, MAX_MATCHES)
        if search
        else diagnosis.top_scorers(sidebar_season, TOP_SCORERS)
    )
    labels = {pick_id(r["season"], r["player_id"]): _label(r) for _, r in rows.iterrows()}
    options = list(labels)
    # A pick the new search no longer lists goes back to the default.
    if st.session_state.get(key) not in options:
        st.session_state.pop(key, None)
    if not options:
        st.caption(f'No player matches "{search}".')
        return None
    # The tab opens on the season's top two: A the first, B the second.
    default = 1 if side == "B" and not search and len(options) > 1 else 0
    st.session_state.setdefault(key, options[default])
    pick = st.selectbox(
        f"Player-season {side}",
        options,
        key=key,
        format_func=labels.__getitem__,
        label_visibility="collapsed",
    )
    if search and len(options) == MAX_MATCHES:
        st.caption(f"The newest {MAX_MATCHES} matches. Add more of the name to narrow it.")
    return parse_pick(pick)


def _who(row: pd.Series, color: str) -> str:
    """The side's name, season, team and games, in its colour, with the note
    when it has no percentiles."""
    swatch = (
        f'<span style="display:inline-block;width:10px;height:10px;background:{color};'
        f'margin-right:8px"></span>'
    )
    line = (
        f"{swatch}<b>{html.escape(row['player'])}</b> "
        f'<span style="color:{T.MUTED}">{row["season"]} · {html.escape(row["team_label"])}'
        f" · {int(row['games_played'])} GP</span>"
    )
    if not row["is_qualified"]:
        line += f'<br><span style="color:{T.MUTED}">{NOT_QUALIFIED}</span>'
    return line


def _section(title: str, help: str = "") -> None:
    st.markdown(f"#### {title}{T.tip(help) if help else ''}", unsafe_allow_html=True)


def _key_row(items: list[tuple[str, str]]) -> None:
    """Names with a hover each, for the labels a chart can't hold a tip on."""
    cells = "".join(f"<span>{label}{T.tip(text)}</span>" for label, text in items)
    st.markdown(
        f'<div style="display:flex;flex-wrap:wrap;gap:4px 16px;color:{T.MUTED};'
        f'font-size:0.85rem">{cells}</div>',
        unsafe_allow_html=True,
    )


def _name(row: pd.Series) -> str:
    return f"{row['player']} {row['season']}"


def _radar(rows: list[pd.Series], colors: list[str]) -> None:
    """The percentile radar, or the one line saying why there isn't one."""
    _section("Where each ranks", glossary.TERMS["Player percentile"])
    ranked = [(r, c) for r, c in zip(rows, colors, strict=True) if r["is_qualified"]]
    if not ranked:
        st.info("Neither player-season has enough games for percentiles, so there is no radar.")
        return
    axes, dropped = available_axes([r for r, _ in ranked])
    gone = "; for ".join(f"{season}: {', '.join(names)}" for season, names in dropped.items())
    if len(axes) < MIN_SPOKES:
        st.info(
            f"Too few percentiles exist for a radar (not available for {gone}). "
            "The stat line still compares them."
        )
        return
    sides = []
    for row, color in ranked:
        values, hovers = [], []
        for axis in axes:
            pct = float(row[f"{axis.column}_pctile"])
            values.append(pct)
            hovers.append(
                f"{axis.label} {format_value(axis.column, float(row[axis.column]))}"
                f" · {ordinal(round(pct))} percentile"
            )
        sides.append(viz_compare.RadarSide(_name(row), color, values, hovers))
    fig = viz_compare.compare_radar([a.name for a in axes], sides)
    st.plotly_chart(fig, config=viz.PLOTLY_CONFIG, width="stretch")
    st.caption(METHOD)
    if dropped:
        st.caption(f"Not available for {gone}.")
    _key_row([(f"{a.name} ({a.label})", glossary.TERMS[a.term]) for a in axes])


def _stat_line(rows: list[pd.Series], colors: list[str]) -> None:
    """The per-game line, side by side."""
    _section("Per game")
    stats = []
    for label, column in STAT_LINE:
        values = [None if pd.isna(r[column]) else float(r[column]) for r in rows]
        texts = ["-" if v is None else format_value(column, v) for v in values]
        stats.append(viz_compare.BarStat(label, values, texts))
    sides = [viz_compare.BarSide(_name(r), c) for r, c in zip(rows, colors, strict=True)]
    fig = viz_compare.compare_bars(stats, sides)
    st.plotly_chart(fig, config=viz.PLOTLY_CONFIG, width="stretch")
    _key_row([(label, glossary.TERMS[METRICS[column].term]) for label, column in STAT_LINE])


def render_compare() -> None:
    """The Compare tab."""
    if not diagnosis.percentiles_available():
        st.info("The player compare arrives with the next data refresh.")
        return
    sidebar = st.session_state.get(shared_state.SEASON_KEY) or seasons.seasons()[0]
    left, right = st.columns(2)
    with left:
        a_pick = _picker("A", A_KEY, A_SEARCH_KEY, sidebar)
        a_head = st.container()
    with right:
        b_pick = _picker("B", B_KEY, B_SEARCH_KEY, sidebar)
        b_head = st.container()
    if a_pick is None or b_pick is None:
        st.info("Pick a player-season on each side to compare them.")
        return

    a_row, b_row = (diagnosis.compare_line(*pick) for pick in (a_pick, b_pick))
    if a_row is None or b_row is None:
        st.info("One of those player-seasons is not in the warehouse. Pick another.")
        return
    rows = [a_row, b_row]
    colors = list(side_colors(a_row["team"], b_row["team"]))
    a_head.markdown(_who(a_row, colors[0]), unsafe_allow_html=True)
    b_head.markdown(_who(b_row, colors[1]), unsafe_allow_html=True)
    if a_pick == b_pick:
        st.caption("Both sides are the same player-season. Pick another to compare.")

    radar, line = st.columns(2)
    with radar:
        _radar(rows, colors)
    with line:
        _stat_line(rows, colors)
