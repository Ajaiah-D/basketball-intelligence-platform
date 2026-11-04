"""The Players page's Player tab: one player in depth, at one season or
across his career, laid out as one titled section per question.

  Season:  header, summary tiles, Game by game, Shooting, Advanced, Game log
  Career:  header, summary tiles, Career trajectory and the career tiles

The player is the one the search, a click on an All players row or another
page chose (search.PLAYER_ID_KEY / PLAYER_SEASON_KEY). When nobody has been
chosen yet it is the top row of the All players table, at the table's scope
(a career table opens his career, as a click on that row would), then the
sidebar season's top scorer.
"""

from __future__ import annotations

from typing import NamedTuple

import pandas as pd
import streamlit as st
from streamlit.delta_generator import DeltaGenerator

from core.constants import COMPLETE_BOX_SCORE_FIRST_SEASON
from dashboard.lib import glossary, media, viz
from dashboard.lib import theme as T
from dashboard.lib.advanced_metrics import COMPARE_METRICS, advanced_percentiles, minutes_floor
from dashboard.lib.data import advanced, players
from dashboard.lib.stats import ShootingRank, percentile_of, qualification_threshold
from dashboard.views.players import game_log
from dashboard.views.players.search import PLAYER_ID_KEY, PLAYER_SCOPE_KEY, PLAYER_SEASON_KEY

# The career trajectory's stat picker.
CAREER_TREND_KEY = "players_career_stat"
# The tab's widgets, which the page keeps as they were while another tab is
# open (table.keep_filters), so Player (Career) -> Compare -> Player comes
# back on Career with the same stat picked.
KEPT_KEYS = [PLAYER_SCOPE_KEY, game_log.TREND_KEY, CAREER_TREND_KEY]

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


class _Ranked(NamedTuple):
    """How one shooting percentage is ranked."""

    label: str
    pct_col: str
    # Only players with at least `floor` of these attempts in a full season
    # are ranked, and ranked against (shooting_floors scales it down for a
    # season under way).
    volume_col: str
    floor: int
    # His attempts per game and the league's figure, where there is one.
    attempts_col: str | None
    league_col: str | None


# Shooting percentiles are measured against players who actually shoot that
# often. A league average answers "above or below"; it cannot tell you that
# 36% from three is roughly league-median while 40% is near the top.
SHOOTING_RANKS = [
    _Ranked("FG%", "fg_pct", "fga_total", 300, "fga_pg", "fg_pct"),
    _Ranked("3P%", "fg3_pct", "tpa_total", 100, "tpa_pg", "fg3_pct"),
    _Ranked("FT%", "ft_pct", "fta_total", 100, "fta_pg", "ft_pct"),
    # True shooting counts field goals and free throws together, so it has
    # no one attempts figure, and the league table has no true shooting.
    _Ranked("TS%", "ts_pct", "fga_total", 300, None, None),
]


# stats.qualification_threshold's games floor for a full season.
_FULL_SEASON_GAMES = 25


def shooting_floors(pool: pd.DataFrame) -> dict[str, int]:
    """The attempts floor for each SHOOTING_RANKS percentage in the season
    whose players are `pool`. A season under way asks for the same share of
    each floor as its games floor asks of a full season's 25 games
    (stats.qualification_threshold): nobody has 300 field goal attempts in
    the first weeks, and a fixed floor would rank nobody until December."""
    share = qualification_threshold(pool) / _FULL_SEASON_GAMES if len(pool) else 1.0
    return {r.label: max(1, round(r.floor * min(1.0, share))) for r in SHOOTING_RANKS}


def _number(v) -> float | None:
    """`v` as a float, or None when it is missing."""
    return None if v is None or pd.isna(v) else float(v)


def rank_shooting(row: pd.Series, pool: pd.DataFrame, league: pd.Series) -> list[ShootingRank]:
    """Each SHOOTING_RANKS percentage of `row` ranked among the players in
    `pool` over the same attempts floor (shooting_floors), with his attempts
    per game and the `league` figure. A percentage he is under the floor for
    is left out."""
    floors = shooting_floors(pool)
    out = []
    for r in SHOOTING_RANKS:
        floor = floors[r.label]
        value = _number(row.get(r.pct_col))
        if value is None or (_number(row.get(r.volume_col)) or 0) < floor:
            continue
        qualified = pool[pool[r.volume_col] >= floor][r.pct_col]
        rank = percentile_of(qualified, value, higher_is_better=True)
        if rank is None:
            continue
        out.append(
            ShootingRank(
                r.label,
                rank,
                value,
                _number(row.get(r.attempts_col)) if r.attempts_col else None,
                _number(league.get(r.league_col)) if r.league_col else None,
            )
        )
    return out


def shooting_percentiles(season: str, row: pd.Series) -> list[ShootingRank]:
    """rank_shooting against `season`'s players and league figures."""
    return rank_shooting(
        row, players.player_season_stats(season), players.league_shooting_averages(season)
    )


def _fmt(v, suffix=""):
    return f"{v:.1f}{suffix}" if v == v else "-"


def _title_row(title: str) -> DeltaGenerator:
    """An h4 section title with room on its right, on the same row, for the
    section's control (a stat picker). Under 640px wide Streamlit stacks the
    two, and the control sits just under the title."""
    t, p = st.columns([3, 2], vertical_alignment="center")
    t.markdown(f"#### {title}")
    return p


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
    picker = _title_row("Career trajectory")
    if st.session_state.get(CAREER_TREND_KEY) not in TREND_STATS:
        st.session_state[CAREER_TREND_KEY] = "PPG"
    stat_label = (
        picker.segmented_control(
            "Stat",
            list(TREND_STATS),
            required=True,
            label_visibility="collapsed",
            key=CAREER_TREND_KEY,
        )
        or "PPG"
    )
    stat_col, weight_col, is_rate = TREND_STATS[stat_label]
    bk = players.player_season_breakdown(int(row.player_id))
    st.plotly_chart(
        viz.career_trend(bk, stat_col, stat_label, weight=weight_col, as_rate=is_rate),
        config=viz.PLOTLY_CONFIG,
        width="stretch",
    )
    st.caption(
        "One mark per season: his average that season. The line is his career "
        "average to date."
        + (
            " True shooting weights the running average by shot volume, so a "
            "short season does not count the same as a full one. Any season the "
            "source has no attempt totals for is left out rather than drawn as zero."
            if stat_label == "TS%"
            else ""
        )
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


def _shooting(row, row_season: str) -> None:
    """His shooting percentages ranked among qualified shooters, in one chart."""
    floors = shooting_floors(players.player_season_stats(row_season))
    rule = f"{floors['FG%']}+ FGA (FG%, TS%), {floors['3P%']}+ 3PA, {floors['FT%']}+ FTA"
    full = {r.label: r.floor for r in SHOOTING_RANKS}
    if floors != full:
        rule += f"; a full season asks for {full['FG%']} / {full['3P%']} / {full['FT%']}"
    ranks = shooting_percentiles(row_season, row)
    if not ranks:
        st.caption(f"Too few attempts to rank. Ranking needs {rule}.")
        return
    st.plotly_chart(
        viz.shooting_percentiles_chart(ranks), config=viz.PLOTLY_CONFIG, width="stretch"
    )
    st.caption(
        f"Ranked among the season's players with {rule}. League figures are "
        "volume-weighted: all makes over all attempts."
    )


def _advanced(row, row_season: str) -> None:
    """The advanced profile (the comparison metrics as percentiles), against
    players over the season's minutes floor."""
    if not advanced.marts_available():
        st.caption("No advanced stats in this copy of the warehouse yet.")
        return
    if row_season not in advanced.advanced_seasons():
        st.caption(
            f"No advanced stats for {row_season}: they start in "
            f"{COMPLETE_BOX_SCORE_FIRST_SEASON}, the first season with complete box scores."
        )
        return
    season_pool = advanced.player_advanced(row_season)
    floor = minutes_floor(season_pool)
    mine = season_pool[season_pool["player_id"] == int(row.player_id)]
    if mine.empty:
        st.caption(f"No advanced stats for him in {row_season}.")
        return
    me = mine.iloc[0]
    if me["minutes"] < floor:
        st.caption(f"Under {floor} minutes: too few to rank.")
        return
    pool = season_pool[season_pool["minutes"] >= floor]
    st.plotly_chart(
        viz.percentile_bars(
            advanced_percentiles(me, pool),
            axis_title=f"Percentile among players with {floor}+ minutes",
        ),
        config=viz.PLOTLY_CONFIG,
        width="stretch",
    )
    # Only a ranked metric where lower is better needs saying so.
    lower = " Lower is better for TOV%." if "TOV%" in COMPARE_METRICS else ""
    st.caption(
        f"Percentile among players with {floor}+ minutes this season; the number "
        f"is the raw value.{lower}"
    )


def _season_detail(row, row_season: str) -> None:
    # A warehouse published before mart_player_game has no games to list:
    # one notice, and the season-level sections still draw.
    has_games = players.player_games_available()
    games = players.player_games(int(row.player_id), row_season) if has_games else None
    figures = game_log.season_figures(row)

    picker = _title_row("Game by game")
    if games is None:
        st.info("The game log and game-by-game trend arrive with the next data refresh.")
    else:
        game_log.render_trend(games, figures, game_log.trend_picker(games, picker))

    st.markdown("#### Shooting")
    _shooting(row, row_season)

    st.markdown("#### Advanced")
    _advanced(row, row_season)

    if games is not None:
        st.markdown("#### Game log")
        _game_tiles(games)
        game_log.render_game_log(games, figures)


class _Pick(NamedTuple):
    player_id: int
    season: str
    # For a default player (nobody chosen yet), whether the table he came
    # from was a career table; None for a chosen player, whose scope is the
    # toggle's.
    table_career: bool | None


def _picked(default_rows: pd.DataFrame | None, season: str) -> _Pick | None:
    """The player to show: the chosen one, else the top row of the All
    players table when it lists the sidebar season (or careers), else the
    season's top scorer among players over the games floor."""
    player_id = st.session_state.get(PLAYER_ID_KEY)
    if player_id is not None:
        return _Pick(int(player_id), st.session_state.get(PLAYER_SEASON_KEY) or season, None)
    if default_rows is not None and len(default_rows):
        top = default_rows.iloc[0]
        if "season" not in default_rows:  # Career scope
            return _Pick(int(top["player_id"]), str(top["last_season"]), True)
        # A table drawn before the sidebar season changed is stale.
        if top["season"] == season:
            return _Pick(int(top["player_id"]), season, False)
    stats = players.player_season_stats(season)
    if stats.empty:
        return None
    pool = stats[stats["gp"] >= qualification_threshold(stats)]
    top = (pool if len(pool) else stats).sort_values("ppg", ascending=False).iloc[0]
    return _Pick(int(top["player_id"]), season, False)


def _choose(player_id: int, season: str) -> None:
    """The scope toggle's on_change: whoever is on screen becomes the chosen
    player, so a default player keeps the scope the reader just picked
    instead of following the table's again on the next run."""
    st.session_state[PLAYER_ID_KEY] = player_id
    st.session_state[PLAYER_SEASON_KEY] = season


def _career_row(player_id: int) -> pd.Series | None:
    career = players.player_career_stats()
    match = career[career["player_id"] == player_id]
    if match.empty:
        return None
    return players.with_career_labels(match).iloc[0]


def render_player(default_rows: pd.DataFrame | None, season: str) -> None:
    """The Player tab at the page's `season`. `default_rows` is the All
    players table as last drawn (or None), whose top row is shown when nobody
    has been chosen."""
    picked = _picked(default_rows, season)
    if picked is None:
        st.info(f"No player stats for {season} yet.")
        return

    head, toggle = st.columns([4, 1], vertical_alignment="center")
    # Set before the toggle is drawn rather than passed as its default (see
    # table._choice). A default player opens at his table's scope.
    if picked.table_career is not None:
        st.session_state[PLAYER_SCOPE_KEY] = "Career" if picked.table_career else "Season"
    elif st.session_state.get(PLAYER_SCOPE_KEY) not in ("Season", "Career"):
        st.session_state[PLAYER_SCOPE_KEY] = "Season"
    career = (
        toggle.segmented_control(
            "Scope",
            ["Season", "Career"],
            required=True,
            label_visibility="collapsed",
            key=PLAYER_SCOPE_KEY,
            on_change=_choose,
            args=(picked.player_id, picked.season),
        )
        == "Career"
    )

    if career:
        row = _career_row(picked.player_id)
    else:
        stats = players.player_season_stats(picked.season)
        match = stats[stats["player_id"] == picked.player_id]
        row = match.iloc[0] if len(match) else None
    if row is None:
        st.info(f"No {'career' if career else picked.season} line for this player.")
        return

    _player_header(row, career, season, picked.season, head)
    if career:
        _career_detail(row)
    else:
        _season_detail(row, picked.season)
