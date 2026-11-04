"""The Players page's Player tab: one player in depth, at one season or
across his career.

The player is the one the search, a click on an All players row or another
page chose (search.PLAYER_ID_KEY / PLAYER_SEASON_KEY); when nobody has been
chosen yet, the top row of the All players table, then the sidebar season's
top scorer.
"""

import pandas as pd
import streamlit as st
from streamlit.delta_generator import DeltaGenerator

from dashboard.lib import glossary, media, viz
from dashboard.lib import theme as T
from dashboard.lib.data import players, seasons
from dashboard.lib.state import SEASON_KEY
from dashboard.lib.stats import percentile_of, qualification_threshold
from dashboard.views.players import game_log
from dashboard.views.players.search import PLAYER_ID_KEY, PLAYER_SCOPE_KEY, PLAYER_SEASON_KEY

# label -> (column, running-average weight, is it a rate). Counting stats
# weight by games and draw as bars; TS% weights by the shot volume behind it
# and draws as dots, since a percentage does not belong on a zero baseline.
TREND_STATS = {
    "PPG": ("ppg", "gp", False),
    "RPG": ("rpg", "gp", False),
    "APG": ("apg", "gp", False),
    "3PM/g": ("tpg", "gp", False),
    "TS%": ("ts_pct", "shot_poss", True),
}


# Shooting percentiles are measured against players who actually shoot that
# often. A league average answers "above or below"; it cannot tell you that
# 36% from three is roughly league-median while 40% is near the top.
SHOOTING_RANKS = [
    ("FG%", "fg_pct", "fga_total", 300),
    ("3P%", "fg3_pct", "tpa_total", 100),
    ("FT%", "ft_pct", "fta_total", 100),
    ("TS%", "ts_pct", "fga_total", 300),
]


def shooting_percentiles(season: str, row) -> list[tuple[str, float, float]]:
    pool = players.player_season_stats(season)
    out = []
    for label, pct_col, vol_col, min_vol in SHOOTING_RANKS:
        value = row.get(pct_col)
        if value is None or value != value or row.get(vol_col, 0) < min_vol:
            continue
        qualified = pool[pool[vol_col] >= min_vol][pct_col]
        rank = percentile_of(qualified, value, higher_is_better=True)
        if rank is not None:
            out.append((label, rank, value))
    return out


def _fmt(v, suffix=""):
    return f"{v:.1f}{suffix}" if v == v else "-"


def _player_header(row, career: bool, season: str, row_season: str, head: DeltaGenerator) -> None:
    """Avatar, name and team chip (into `head`, beside the Season / Career
    toggle), the six KPI tiles and the small-sample note."""
    tc = T.team_color(row.team)
    chip_text = (
        f"{row.team} &middot; {row.seasons} seasons &middot; {row.gp} GP"
        if career
        else f"{row.team_label} &middot; {row.gp} GP &middot; {row.mpg:.1f} MPG"
        + (f" &middot; {row_season}" if row_season != season else "")
    )
    head.markdown(
        f'<div style="display:flex;align-items:center;gap:14px;margin:.4rem 0 .8rem 0">'
        f"{media.avatar_html(int(row.player_id), row.player, size=84, ring=tc)}"
        f'<div><span style="font-size:1.6rem;font-weight:800;letter-spacing:-.02em">'
        f"{row.player}</span><br>"
        f"{T.chip(chip_text, tc)}"
        f"</div></div>",
        unsafe_allow_html=True,
    )
    tiles = st.columns(6)
    for col, (label, val, sub) in zip(
        tiles,
        [
            ("PPG", _fmt(row.ppg), f"{row.pts_total:,} career pts" if career else ""),
            ("RPG", _fmt(row.rpg), ""),
            ("APG", _fmt(row.apg), ""),
            ("FG%", _fmt(row.fg_pct), f"on {_fmt(row.fga_pg)} FGA/g"),
            ("3P%", _fmt(row.fg3_pct), f"on {_fmt(row.tpa_pg)} 3PA/g ({row.tpa_total} total)"),
            ("TS%", _fmt(row.ts_pct), "true shooting"),
        ],
        strict=True,
    ):
        col.markdown(
            T.kpi(label, val, sub, help=glossary.TERMS.get(label, "")), unsafe_allow_html=True
        )

    if row.tpa_total and row.tpa_total < 50 and row.fg3_pct == row.fg3_pct:
        when = "across a whole career" if career else "all season"
        st.caption(
            f"Note: {row.player}'s 3P% comes from only {row.tpa_total} "
            f"attempts {when} - treat it as noise, not a skill signal."
        )


def _career_detail(row) -> None:
    bk = players.player_season_breakdown(int(row.player_id))
    st.markdown(
        "**Career trajectory** - bars are season averages, the line is the career average to date"
    )
    stat_label = (
        st.segmented_control("Stat", list(TREND_STATS), default="PPG", label_visibility="collapsed")
        or "PPG"
    )
    stat_col, weight_col, is_rate = TREND_STATS[stat_label]
    st.plotly_chart(
        viz.career_trend(bk, stat_col, stat_label, weight=weight_col, as_rate=is_rate),
        config=viz.PLOTLY_CONFIG,
        width="stretch",
    )
    if stat_label == "TS%":
        st.caption(
            "True shooting weights the running average by shot volume, "
            "so a short season does not count the same as a full one. "
            "Any season the source has no attempt totals for is left "
            "out rather than drawn as zero."
        )

    s1, s2, s3, s4 = st.columns(4)
    s1.markdown(
        T.kpi("Career high", f"{row.career_high}", "points in a game"), unsafe_allow_html=True
    )
    s2.markdown(T.kpi("Seasons", f"{row.seasons}", row.span), unsafe_allow_html=True)
    s3.markdown(T.kpi("Total points", f"{row.pts_total:,}"), unsafe_allow_html=True)
    s4.markdown(T.kpi("Record in games", f"{row.wins}-{row.gp - row.wins}"), unsafe_allow_html=True)


def _game_tiles(games: pd.DataFrame) -> None:
    """Home and away scoring, the season high and his teams' record in his games."""
    home = games[~games.is_away]
    away = games[games.is_away]
    s1, s2, s3, s4 = st.columns(4)
    s1.markdown(
        T.kpi("Home PPG", f"{home.pts.mean():.1f}" if len(home) else "-"), unsafe_allow_html=True
    )
    s2.markdown(
        T.kpi("Away PPG", f"{away.pts.mean():.1f}" if len(away) else "-"), unsafe_allow_html=True
    )
    s3.markdown(T.kpi("Season high", f"{games.pts.max():.0f}"), unsafe_allow_html=True)
    s4.markdown(
        T.kpi("Record in games", f"{int(games.is_win.sum())}-{int((~games.is_win).sum())}"),
        unsafe_allow_html=True,
    )


def _season_detail(row, row_season: str) -> None:
    # A warehouse published before mart_player_game has no games to list:
    # one notice, and the season-level charts still draw.
    has_games = players.player_games_available()
    games = players.player_games(int(row.player_id), row_season) if has_games else None
    figures = game_log.season_figures(row)
    c1, c2 = st.columns([3, 2])
    with c1:
        if games is None:
            st.info("The game log and game-by-game trend arrive with the next data refresh.")
        else:
            game_log.render_trend(games, figures)
    with c2:
        st.markdown("**Shooting vs league** (labels show attempts/game)")
        st.plotly_chart(
            viz.shooting_profile(row, players.league_shooting_averages(row_season), row.player),
            config=viz.PLOTLY_CONFIG,
            width="stretch",
        )
        st.caption(
            "League bars are volume-weighted (total makes / total attempts "
            "across every player), the same basis the NBA uses."
        )

    ranks = shooting_percentiles(row_season, row)
    if ranks:
        st.markdown(
            "**Where that ranks** - percentile among players with 100+ "
            "attempts, which is the context a league average alone leaves out"
        )
        st.plotly_chart(viz.percentile_bars(ranks), config=viz.PLOTLY_CONFIG, width="stretch")

    if games is not None:
        _game_tiles(games)
        game_log.render_game_log(games, figures)


def _picked(default_rows: pd.DataFrame | None, season: str) -> tuple[int, str] | None:
    """(player_id, season) to show: the chosen player, else the top row of
    the All players table when it lists the sidebar season (or careers),
    else the season's top scorer among players over the games floor."""
    player_id = st.session_state.get(PLAYER_ID_KEY)
    if player_id is not None:
        return int(player_id), st.session_state.get(PLAYER_SEASON_KEY) or season
    if default_rows is not None and len(default_rows):
        top = default_rows.iloc[0]
        if "season" not in default_rows:  # Career scope
            return int(top["player_id"]), str(top["last_season"])
        # A table drawn before the sidebar season changed is stale.
        if top["season"] == season:
            return int(top["player_id"]), season
    stats = players.player_season_stats(season)
    if stats.empty:
        return None
    pool = stats[stats["gp"] >= qualification_threshold(stats)]
    top = (pool if len(pool) else stats).sort_values("ppg", ascending=False).iloc[0]
    return int(top["player_id"]), season


def _career_row(player_id: int) -> pd.Series | None:
    career = players.player_career_stats()
    match = career[career["player_id"] == player_id]
    if match.empty:
        return None
    row = match.iloc[0].copy()
    row["team_label"] = row["team"]
    row["span"] = (
        row["first_season"]
        if row["seasons"] == 1
        else f"{row['first_season']} to {row['last_season']}"
    )
    return row


def render_player(default_rows: pd.DataFrame | None) -> None:
    """The Player tab. `default_rows` is the All players table as last drawn
    (or None), whose top row is shown when nobody has been chosen."""
    season = st.session_state.get(SEASON_KEY) or seasons.latest_season()
    picked = _picked(default_rows, season)
    if picked is None:
        st.info(f"No player stats for {season} yet.")
        return
    player_id, row_season = picked

    head, toggle = st.columns([5, 1], vertical_alignment="center")
    # Set before the toggle is drawn rather than passed as its default (see
    # table._choice). A click on the selected option clears it; that falls
    # back to Season.
    if st.session_state.get(PLAYER_SCOPE_KEY) not in ("Season", "Career"):
        st.session_state[PLAYER_SCOPE_KEY] = "Season"
    career = (
        toggle.segmented_control(
            "Scope", ["Season", "Career"], label_visibility="collapsed", key=PLAYER_SCOPE_KEY
        )
        == "Career"
    )

    if career:
        row = _career_row(player_id)
    else:
        stats = players.player_season_stats(row_season)
        match = stats[stats["player_id"] == player_id]
        row = match.iloc[0] if len(match) else None
    if row is None:
        st.info(f"No {'career' if career else row_season} line for this player.")
        return

    _player_header(row, career, season, row_season, head)
    if career:
        _career_detail(row)
    else:
        _season_detail(row, row_season)
