"""The season detail's game log and game-by-game trend (Players > Stats).

Both read data.players.player_games and set each game against his own
season figure from mart_player_season (the detail's row): the table shades
a stat green or red when the game was clearly above or below that figure,
and the chart draws it as a dashed line. That is all they say: whether a
night was good is left to the reader.
"""

from __future__ import annotations

from collections.abc import Mapping

import pandas as pd
import streamlit as st

from dashboard.lib import glossary, tables, viz, viz_diagnosis
from dashboard.lib.tables import Col
from dashboard.lib.viz_diagnosis import GAME_STATS

TREND_KEY = "players_trend_stat"
# Tall enough for about ten games, short enough that a full season doesn't
# run the page on: the rest scroll inside it.
LOG_HEIGHT = 420

# A game within 15% of his season figure is a normal night and stays plain.
BAND = 0.15
# ...but never a band under half a unit: a whole-number box score can't sit
# closer than that to an average like 1.2 assists, so 1 assist is normal.
MIN_BAND = 0.5
# +/- crosses zero, so a share of the average means nothing there (15% of
# +0.4 is a tenth of a point): a fixed 3 points either side instead.
PLUS_MINUS_BAND = 3.0

# His season figure for each stat, by its column in mart_player_season's
# row (data.players.player_season_stats).
SEASON_COLUMNS = {
    "PTS": "ppg",
    "REB": "rpg",
    "AST": "apg",
    "3PM": "tpg",
    "TS%": "ts_pct",
    "+/-": "plus_minus",
}


def _missing(v) -> bool:
    return v is None or bool(pd.isna(v))


def tint(value, avg, stat: str) -> str:
    """ "above", "below" or "" for one game's `stat` against his season
    figure `avg`: the cell's class. Plain when either is missing (no shots
    means no TS% to set against anything)."""
    if _missing(value) or _missing(avg):
        return ""
    band = PLUS_MINUS_BAND if stat == "+/-" else max(BAND * abs(avg), MIN_BAND)
    if value > avg + band:
        return "above"
    if value < avg - band:
        return "below"
    return ""


def season_figures(row) -> dict[str, float]:
    """His season figure for every GAME_STATS stat, from the detail's row."""
    return {stat: float(getattr(row, col)) for stat, col in SEASON_COLUMNS.items()}


def _whole(v) -> str:
    return "-" if _missing(v) else f"{int(v)}"


def _one_decimal(v) -> str:
    return "-" if _missing(v) else f"{v:.1f}"


def _date(d) -> str:
    return f"{d:%b} {d.day}"


def _result(r) -> str:
    """His team's score first ("W 112-104"); the result alone without one."""
    wl = "W" if r.is_win else "L"
    if _missing(r.team_pts) or _missing(r.opp_pts):
        return wl
    return f"{wl} {int(r.team_pts)}-{int(r.opp_pts)}"


def _stat_col(stat: str, avg: float) -> Col:
    spec = GAME_STATS[stat]
    fmt = tables.signed if stat == "+/-" else _one_decimal if spec.decimals else _whole
    return Col(
        spec.col,
        stat,
        fmt=fmt,
        help=glossary.TERMS[stat],
        css=lambda v: tint(v, avg, stat),
    )


def game_log_html(games: pd.DataFrame, figures: Mapping[str, float]) -> str:
    """Every game in `games` (data.players.player_games, oldest first),
    newest first, in a table that scrolls inside LOG_HEIGHT. `figures` is
    season_figures(row)."""
    newest = games.iloc[::-1]
    rows = newest.assign(
        when=newest["game_date"].map(_date),
        vs=[
            f"{'@' if away else 'vs'} {opp}"
            for away, opp in zip(newest["is_away"], newest["opp"], strict=True)
        ],
        result=[_result(r) for r in newest.itertuples(index=False)],
    )
    cols = [
        Col("when", "Date", left=True),
        Col("vs", "Opp", left=True),
        Col("result", "Result", left=True),
        # Minutes stay plain: playing time is context, not better or worse.
        Col("min", "MIN", fmt=_whole, help=glossary.TERMS["MIN"]),
        *(_stat_col(stat, figures[stat]) for stat in GAME_STATS),
    ]
    return tables.html_table(rows, cols, max_height=LOG_HEIGHT)


def render_game_log(games: pd.DataFrame, figures: Mapping[str, float]) -> None:
    st.markdown("**Game log**")
    st.markdown(game_log_html(games, figures), unsafe_allow_html=True)
    st.caption(
        "Green or red: above or below his own season average, by more than "
        "about 15% (3 points for +/-)."
    )


def render_trend(games: pd.DataFrame, figures: Mapping[str, float]) -> None:
    """The stat picker and the chart of that stat game by game."""
    options = list(GAME_STATS)
    st.session_state.setdefault(TREND_KEY, options[0])
    stat = st.selectbox(
        "Stat",
        options,
        key=TREND_KEY,
        help=glossary.TERMS[st.session_state[TREND_KEY]],
        width=200,
    )
    st.plotly_chart(
        viz_diagnosis.stat_trend(games, stat, figures[stat]),
        config=viz.PLOTLY_CONFIG,
        width="stretch",
    )
