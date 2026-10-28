"""The Players page's Scatter tab: every player in a season on any two
stats, to see where each one sits. The dashed lines are the average of the
players shown and the only reference; nothing is called good or bad.

The tab has its own season box. It starts at the sidebar's season and
follows the sidebar when that changes, but it never writes back, so looking
at another year here leaves the Stats tab where it was.
"""

from typing import NamedTuple

import plotly.graph_objects as go
import streamlit as st

from dashboard.lib import glossary, viz, viz_diagnosis
from dashboard.lib import state as shared_state
from dashboard.lib import theme as T
from dashboard.lib.data import diagnosis, players, seasons
from dashboard.lib.stats import qualification_threshold

SEASON_KEY = "players_scatter_season"
X_KEY = "players_scatter_x"
Y_KEY = "players_scatter_y"
MIN_GP_KEY = "players_scatter_min_gp"
TEAM_KEY = "players_scatter_team"
# The sidebar season last seen, and the season the min-games slider was last
# defaulted for: a change in either resets what depends on it.
_SIDEBAR_SEEN_KEY = "players_scatter_sidebar_season"
_MIN_GP_FOR_KEY = "players_scatter_min_gp_season"

ALL_TEAMS = "All"
DEFAULT_X = "points_per_game"
DEFAULT_Y = "true_shooting_pct"
CHART_HEIGHT = 520
# Smaller than the team scatters' dots, since a season has ~400 players to
# their 30 teams.
DOT_PX = 8


class Metric(NamedTuple):
    """A stat the scatter offers: its label, its glossary.TERMS entry and how
    its values print ("plain" 20.9, "pct" 59.4%, "ratio" 0.264, "signed" +2.0)."""

    label: str
    term: str
    kind: str


# In the pickers' order, keyed by the column data.diagnosis.league_player_rows
# returns.
METRICS: dict[str, Metric] = {
    "points_per_game": Metric("PTS", "PTS", "plain"),
    "rebounds_per_game": Metric("REB", "REB", "plain"),
    "assists_per_game": Metric("AST", "AST", "plain"),
    "steals_per_game": Metric("STL", "STL", "plain"),
    "blocks_per_game": Metric("BLK", "BLK", "plain"),
    "threes_made_per_game": Metric("3PM", "3PM", "plain"),
    "true_shooting_pct": Metric("TS%", "TS%", "pct"),
    "effective_fg_pct": Metric("eFG%", "eFG%", "pct"),
    "usage_pct": Metric("USG%", "USG%", "pct"),
    "assist_pct": Metric("AST%", "AST%", "pct"),
    "rebound_pct": Metric("REB%", "REB%", "pct"),
    "turnover_pct": Metric("TOV%", "TOV%", "pct"),
    "steal_pct": Metric("STL%", "STL%", "pct"),
    "block_pct": Metric("BLK%", "BLK%", "pct"),
    "three_point_attempt_rate": Metric("3PA rate", "3PA rate (player)", "ratio"),
    "free_throw_rate": Metric("FT rate", "FT rate (player)", "ratio"),
    "plus_minus": Metric("+/-", "+/-", "signed"),
    "player_impact_estimate": Metric("PIE", "PIE", "pct"),
    "game_score": Metric("Game score", "Game score", "plain"),
    "minutes_per_game": Metric("Minutes", "MIN", "plain"),
}

# Among these only turnover rate is lower-is-better. The player frame has no
# rank columns to derive that from (the team scatter reads it off its
# ranks), so it is named here.
LOWER_IS_BETTER = ("turnover_pct",)


def format_value(key: str, value: float) -> str:
    """A stat's value as the hover prints it ("20.9", "59.4%", "0.264")."""
    kind = METRICS[key].kind
    if kind == "pct":
        return f"{value:.1f}%"
    if kind == "ratio":
        return f"{value:.3f}"
    if kind == "signed":
        return f"{value:+.1f}"
    return f"{value:.1f}"


def _pick(label: str, key: str, default: str) -> str:
    """A compact stat picker whose hover explains the stat now selected."""
    st.session_state.setdefault(key, default)
    return st.selectbox(
        label,
        list(METRICS),
        key=key,
        format_func=lambda k: METRICS[k].label,
        help=glossary.TERMS[METRICS[st.session_state[key]].term],
    )


def _pick_season() -> str:
    """The tab's season box, at the sidebar's season until the reader picks
    another here."""
    every = seasons.seasons()
    sidebar = st.session_state.get(shared_state.SEASON_KEY) or every[0]
    # A new sidebar season (the Stats tab's box counts) takes this one with it.
    if st.session_state.get(_SIDEBAR_SEEN_KEY) != sidebar:
        st.session_state[_SIDEBAR_SEEN_KEY] = sidebar
        st.session_state[SEASON_KEY] = sidebar
    if st.session_state.get(SEASON_KEY) not in every:
        st.session_state[SEASON_KEY] = sidebar
    return st.selectbox("Season", every, key=SEASON_KEY)


def _pick_min_games(season: str) -> int:
    """The minimum-games slider, set to the qualification rule whenever the
    season changes and the reader's own after that."""
    # Streamlit drops a widget's state on a run where it isn't rendered (another
    # tab or page); the slider would come back at 1, so a lost value resets too.
    if st.session_state.get(_MIN_GP_FOR_KEY) != season or MIN_GP_KEY not in st.session_state:
        st.session_state[_MIN_GP_FOR_KEY] = season
        st.session_state[MIN_GP_KEY] = qualification_threshold(players.player_season_stats(season))
    return st.slider(
        "Min games",
        1,
        82,
        key=MIN_GP_KEY,
        help="Players with fewer games are left out, so a small sample doesn't set the axes",
    )


def _teams_of(label: str) -> list[str]:
    """The teams in a team_label ("CHI → BOS" is both)."""
    return [t.strip() for t in label.split("→")]


# Around the dot, in the order the labels take them from left to right.
_LABEL_SPOTS = ("top center", "bottom center", "middle right", "middle left")


def _stagger_labels(trace: go.Scatter) -> None:
    """Spread the named dots' labels around their dots, left to right, so
    neighbours (a team's rotation sits in one clump) don't print over each
    other, and turn the ones at the right edge inward so a long name isn't
    cut off. An empty trace (every drawn player on the picked team leaves
    the faded rest with none) is left as it is."""
    if trace.x is None or not len(trace.x):
        return
    xs = [float(v) for v in trace.x]
    low, span = min(xs), (max(xs) - min(xs)) or 1.0
    named = sorted((i for i, text in enumerate(trace.text) if text), key=lambda i: xs[i])
    positions = ["top center"] * len(xs)
    for order, i in enumerate(named):
        spot = _LABEL_SPOTS[order % len(_LABEL_SPOTS)]
        if (xs[i] - low) / span > 0.85:
            spot = spot.replace("right", "left").replace("center", "left")
        positions[i] = spot
    trace.textposition = positions


def render_scatter() -> None:
    """The Scatter tab."""
    left, right = st.columns(2)
    with left:
        x = _pick("Horizontal", X_KEY, DEFAULT_X)
    with right:
        y = _pick("Vertical", Y_KEY, DEFAULT_Y)
    season_box, games_box, team_box = st.columns(3)
    with season_box:
        season = _pick_season()
    with games_box:
        min_games = _pick_min_games(season)

    rows = diagnosis.league_player_rows(season, min_games)
    teams = [
        ALL_TEAMS,
        *sorted({t for label in rows["team_label"].dropna() for t in _teams_of(label)}),
    ]
    # A team nobody on it has the new minimum games for is no longer offered.
    if st.session_state.get(TEAM_KEY) not in teams:
        st.session_state.pop(TEAM_KEY, None)
    st.session_state.setdefault(TEAM_KEY, ALL_TEAMS)
    with team_box:
        team = st.selectbox(
            "Team",
            teams,
            key=TEAM_KEY,
            help="Highlights and names every player who played for the team that season",
        )

    if rows.empty:
        st.info(f"No player has {min_games}+ games in {season}. Lower the minimum.")
        return

    # The chart skips players missing either stat (usage, AST% and PIE are null
    # in the older seasons), so the count is of the dots drawn.
    drawn = int(rows[[x, y]].notna().all(axis=1).sum())
    if not drawn:
        st.info(f"No player has both {METRICS[x].label} and {METRICS[y].label} in {season}.")
        return

    caption = f"{drawn} players with {min_games}+ games"
    caption += f", {team} highlighted." if team != ALL_TEAMS else "."
    st.caption(f"{caption} Dashed lines are the average of these players.")

    # What the hover prints, and the one column the highlight matches on: the
    # picked team for each of its players (a traded one is on both teams),
    # blank for the rest.
    rows = rows.assign(
        hover_name=rows["player"] + " (" + rows["team_label"] + ")",
        games=rows["games_played"].astype(int).astype(str) + " GP",
        on_team=rows["team_label"].map(lambda label: team if team in _teams_of(label) else ""),
    )
    fig = viz_diagnosis.stat_scatter(
        rows,
        x,
        y,
        label_col="player",
        color_col="team",
        highlight=None if team == ALL_TEAMS else team,
        highlight_col="on_team",
        x_label=METRICS[x].label,
        y_label=METRICS[y].label,
        invert=tuple(k for k in (x, y) if k in LOWER_IS_BETTER),
        name_col="hover_name",
        fmt=format_value,
        detail_col="games",
        # A traded player's dot would carry his last team's colour; with a team
        # picked, all of its players take that team's.
        highlight_color=None if team == ALL_TEAMS else T.team_color(team),
        # The min-games filter leaves part of the league: the lines average
        # the players drawn.
        average_label="average of these players",
    )
    if fig.data:
        fig.data[0].marker.size = DOT_PX
        for trace in fig.data:
            _stagger_labels(trace)
        if len(fig.data) > 1:
            # With a team picked, the rest fade so its players stand out.
            fig.data[0].marker.opacity = 0.4
    fig.update_layout(height=CHART_HEIGHT)
    st.plotly_chart(fig, config=viz.PLOTLY_CONFIG, width="stretch")
