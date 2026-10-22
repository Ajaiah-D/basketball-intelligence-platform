"""Advanced - rate metrics, leaderboards and a two-player comparison.

Deliberately narrow: one table with a curated column set, a leaderboard
strip, and a head-to-head. The full metric list stays behind a toggle so
the default view is readable rather than exhaustive.

Rate stats need a minutes floor to mean anything (one made three-pointer
on the season is a 150% true shooting percentage), so every view here is
gated on minutes played rather than showing the whole league.
"""

import pandas as pd
import streamlit as st

from core.constants import ADVANCED_STATS_FIRST_SEASON, COMPLETE_BOX_SCORE_FIRST_SEASON
from dashboard.lib import glossary, media, viz
from dashboard.lib import theme as T
from dashboard.lib.data import advanced, seasons
from dashboard.lib.stats import percentile_of

# The default table: enough to answer "who is efficient and how involved
# were they" without becoming a spreadsheet.
CORE_COLS = [
    "player_name",
    "team_label",
    "games_played",
    "minutes_per_game",
    "points_per_game",
    "true_shooting_pct",
    "effective_fg_pct",
    "usage_pct",
    "assist_pct",
    "rebound_pct",
    "game_score",
]

EXTRA_COLS = [
    "turnover_pct",
    "steal_pct",
    "block_pct",
    "points_per_36",
    "points_per_100",
    "net_rating",
    "player_impact_estimate",
]

# Percentile comparison uses metrics that exist for every complete season,
# so the head-to-head still works for pre-1997 players.
COMPARE_METRICS = ["TS%", "USG%", "AST%", "REB%", "STL%", "BLK%", "Game score"]

# Label -> (column, higher_is_better, help text). Drives the Advanced page so
# the metric list lives in one place instead of being restated per widget.
ADVANCED_METRICS: dict[str, tuple[str, bool, str]] = {
    "TS%": (
        "true_shooting_pct",
        True,
        "True shooting: points per shooting possession, counting 3s and free throws",
    ),
    "eFG%": (
        "effective_fg_pct",
        True,
        "Effective FG%: field goal percentage with 3-pointers weighted 1.5x",
    ),
    "USG%": (
        "usage_pct",
        True,
        "Usage: share of team possessions a player ends while on the floor",
    ),
    "AST%": (
        "assist_pct",
        True,
        "Assist rate: share of teammate field goals a player assisted while on the floor",
    ),
    "REB%": (
        "rebound_pct",
        True,
        "Rebound rate: share of available rebounds a player grabbed while on the floor",
    ),
    "TOV%": (
        "turnover_pct",
        False,
        "Turnover rate: turnovers per 100 individual plays (lower is better)",
    ),
    "STL%": ("steal_pct", True, "Steals per opponent possession while on the floor"),
    "BLK%": ("block_pct", True, "Share of opponent 2-point attempts blocked"),
    "PTS/36": ("points_per_36", True, "Points per 36 minutes, pace of a starter's night"),
    "PTS/100": ("points_per_100", True, "Points per 100 team possessions on the floor"),
    "Game score": (
        "game_score",
        True,
        "Hollinger game score: one-number box score summary, ~10 is average",
    ),
    "Net rating": (
        "net_rating",
        True,
        "Team point differential per 100 possessions with the player on the floor "
        f"(official NBA figure, {ADVANCED_STATS_FIRST_SEASON} on)",
    ),
    "PIE": (
        "player_impact_estimate",
        True,
        "Player impact estimate: share of the game's total production "
        f"(official NBA figure, {ADVANCED_STATS_FIRST_SEASON} on)",
    ),
}

COLUMN_CONFIG = {
    "player_name": st.column_config.TextColumn("Player", width="medium"),
    "team_label": st.column_config.TextColumn(
        "Team",
        width="small",
        help="Two teams (CHI → BOS) means traded mid-season; the line covers both",
    ),
    "games_played": st.column_config.NumberColumn(**glossary.described("GP")),
    "minutes_per_game": st.column_config.NumberColumn(**glossary.described("MIN"), format="%.1f"),
    "points_per_game": st.column_config.NumberColumn("PTS", format="%.1f"),
    # Every rate metric is jargon to a casual fan: marked with an icon and
    # explained on header hover (dashboard/lib/glossary.py).
    **{
        col: st.column_config.NumberColumn(**glossary.marked(label), format="%.1f")
        for col, label in [
            ("true_shooting_pct", "TS%"),
            ("effective_fg_pct", "eFG%"),
            ("usage_pct", "USG%"),
            ("assist_pct", "AST%"),
            ("rebound_pct", "REB%"),
            ("game_score", "GmSc"),
            ("turnover_pct", "TOV%"),
            ("steal_pct", "STL%"),
            ("block_pct", "BLK%"),
            ("points_per_36", "P/36"),
            ("points_per_100", "P/100"),
            ("net_rating", "NET"),
            ("player_impact_estimate", "PIE"),
        ]
    },
}


def leader_card(title: str, df, col: str, fmt: str = "{:.1f}") -> str:
    rows = []
    for i, r in enumerate(df.itertuples(), 1):
        rows.append(
            f'<div class="bip-row">{T.rank_badge(i)}'
            f'<span class="bip-name">{r.player_name}</span>'
            f'<span class="bip-team" style="color:{T.team_color(r.team_abbreviation)}">'
            f"{r.team_abbreviation}</span>"
            f'<span class="bip-val">{fmt.format(getattr(r, col))}</span></div>'
        )
    return T.card_html(title, "".join(rows), glossary.TERMS.get(title, ""))


def _season_stats(season: str) -> pd.DataFrame | None:
    """The season's advanced rows, or None after saying why the page has
    nothing to show."""
    # The warehouse can predate these models (an older published copy, or a
    # local build where dbt has not run). Say so here rather than letting a
    # catalog error escape and take down every other page with it.
    if not advanced.marts_available():
        st.info(
            "Advanced metrics are not in this copy of the warehouse yet. "
            "Rebuild it with `dbt run --profiles-dir .` from "
            "`dbt/basketball_intelligence`, or, on a cloud deploy, wait for "
            "the next refresh to publish an updated warehouse."
        )
        return None

    available = advanced.advanced_seasons()

    if season not in available:
        st.info(
            f"Advanced metrics are not available for {season}. The NBA's box "
            "scores are missing rebounds, turnovers and field goal attempts "
            f"before {COMPLETE_BOX_SCORE_FIRST_SEASON}, and those are the inputs every rate "
            "metric needs. "
            f"Pick {available[-1]} or later in the sidebar."
        )
        return None

    # The mart carries team_label ("CHI → BOS" for a traded player).
    stats = advanced.player_advanced(season)
    if stats.empty:
        st.info("No player data for this season yet.")
        return None
    return stats


def _filters(stats: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, int, bool]:
    """The minutes floor, metric toggle and search box. Returns (rows to
    show, the qualified pool percentiles are measured against, the floor,
    whether the extra columns are on)."""
    # A rate stat on 40 minutes is noise, so the floor scales with how much
    # of the season has been played rather than sitting at a fixed number.
    max_min = int(stats["minutes"].max())
    default_floor = min(500, max(50, int(max_min * 0.3)))
    f1, f2, f3 = st.columns([2, 2, 3])
    min_minutes = f1.slider("Minimum minutes", 0, max(100, max_min), default_floor, step=50)
    show_all = f2.toggle(
        "All metrics", value=False, help="Adds turnover, steal, block and per-100 columns"
    )
    search = f3.text_input("Search", placeholder="Search players...", label_visibility="collapsed")

    view = stats[stats.minutes >= min_minutes]
    qualified = view.copy()  # the pool percentiles are measured against
    if search:
        view = view[view.player_name.str.contains(search, case=False, na=False)]
    view = view.sort_values("game_score", ascending=False, na_position="last")
    return view, qualified, min_minutes, show_all


def _table(
    view: pd.DataFrame,
    qualified: pd.DataFrame,
    min_minutes: int,
    show_all: bool,
    has_official: bool,
) -> None:
    cols = CORE_COLS + (EXTRA_COLS if show_all else [])
    # Bar the sort column, matching the Players grid. Scaled to the rows
    # actually in view so it stays a comparison after the minutes filter or a
    # search narrows the table. The floor tracks the data instead of assuming
    # zero: game score goes negative for a bad season, and a 0 floor would
    # render those as an empty bar indistinguishable from a replacement-level
    # one.
    scores = view["game_score"].dropna()
    gs_min = float(min(0.0, scores.min())) if len(scores) else 0.0
    gs_max = float(scores.max()) if len(scores) else 1.0
    if gs_max <= gs_min:
        gs_max = gs_min + 1.0
    column_config = COLUMN_CONFIG | {
        "game_score": st.column_config.ProgressColumn(
            **glossary.marked("GmSc"),
            format="%.1f",
            width="medium",
            min_value=gs_min,
            max_value=gs_max,
            color=T.ACCENT,
        ),
    }
    st.dataframe(
        view[cols], hide_index=True, height=400, row_height=38, column_config=column_config
    )

    source_note = (
        "Net rating and PIE are official NBA figures; everything else is computed from box scores."
        if has_official
        else "All metrics are computed from box scores. The NBA did not publish "
        f"official advanced stats until {ADVANCED_STATS_FIRST_SEASON}."
    )
    st.caption(
        f"{len(qualified)} players with {min_minutes}+ minutes. Sorted by game score. {source_note}"
    )


def _leaders(qualified: pd.DataFrame, min_minutes: int, has_official: bool) -> None:
    st.markdown("#### Efficiency leaders")
    l1, l2, l3, l4 = st.columns(4)
    l1.markdown(
        leader_card(
            "True shooting", qualified.nlargest(5, "true_shooting_pct"), "true_shooting_pct"
        ),
        unsafe_allow_html=True,
    )
    l2.markdown(
        leader_card("Usage", qualified.nlargest(5, "usage_pct"), "usage_pct"),
        unsafe_allow_html=True,
    )
    l3.markdown(
        leader_card("Game score", qualified.nlargest(5, "game_score"), "game_score"),
        unsafe_allow_html=True,
    )
    if has_official and qualified["player_impact_estimate"].notna().any():
        l4.markdown(
            leader_card(
                "Impact (PIE)",
                qualified.nlargest(5, "player_impact_estimate"),
                "player_impact_estimate",
            ),
            unsafe_allow_html=True,
        )
    else:
        l4.markdown(
            leader_card("Rebound rate", qualified.nlargest(5, "rebound_pct"), "rebound_pct"),
            unsafe_allow_html=True,
        )
    st.caption(f"Among players with {min_minutes}+ minutes.")


def _profile(stats: pd.DataFrame, view: pd.DataFrame, qualified: pd.DataFrame) -> bool:
    """One player's header and percentile bars. False when there is nobody
    to pick, so the page stops before the comparison."""
    st.markdown("#### Player profile")
    options = view if len(view) else qualified
    pick: str | None = st.selectbox("Player", options["player_name"], label_visibility="collapsed")
    if not pick:
        return False
    match = qualified[qualified.player_name == pick]
    if match.empty:
        match = stats[stats.player_name == pick]
    row = match.iloc[0]

    tc = T.team_color(row.team_abbreviation)
    st.markdown(
        f'<div style="display:flex;align-items:center;gap:14px;margin:.4rem 0 .8rem 0">'
        f"{media.avatar_html(int(row.player_id), row.player_name, size=72, ring=tc)}"
        f'<div><span style="font-size:1.4rem;font-weight:800;letter-spacing:-.02em">'
        f"{row.player_name}</span><br>"
        f"{
            T.chip(
                f'{row.team_abbreviation} &middot; {row.games_played} GP &middot; '
                f'{row.minutes_per_game:.1f} MPG',
                tc,
            )
        }</div></div>",
        unsafe_allow_html=True,
    )

    rows = []
    for label in COMPARE_METRICS:
        col, higher_better, _ = ADVANCED_METRICS[label]
        val = row.get(col)
        if val is None or val != val:
            continue
        pct = percentile_of(qualified[col], val, higher_better)
        if pct is not None:
            rows.append((label, pct, val))
    st.plotly_chart(viz.percentile_bars(rows), config=viz.PLOTLY_CONFIG, width="stretch")
    st.caption(
        "Bars are percentile rank against the qualified pool; the number in "
        "front is the raw value. TOV% is inverted so longer is always better."
    )
    return True


def _compare(qualified: pd.DataFrame) -> None:
    """Head to head: two players across the comparison metrics."""
    st.markdown("#### Compare two players")
    c1, c2 = st.columns(2)
    names = qualified.sort_values("game_score", ascending=False, na_position="last")[
        "player_name"
    ].tolist()
    if len(names) < 2:
        st.caption("Not enough qualified players to compare at this minutes floor.")
        return
    a_name = c1.selectbox("Player A", names, index=0)
    b_name = c2.selectbox("Player B", names, index=min(1, len(names) - 1))
    if a_name == b_name:
        st.caption("Pick two different players to see the comparison.")
        return

    a = qualified[qualified.player_name == a_name].iloc[0]
    b = qualified[qualified.player_name == b_name].iloc[0]
    labels, a_pcts, b_pcts = [], [], []
    for label in COMPARE_METRICS:
        col, higher_better, _ = ADVANCED_METRICS[label]
        pa = percentile_of(qualified[col], a.get(col), higher_better)
        pb = percentile_of(qualified[col], b.get(col), higher_better)
        if pa is not None and pb is not None:
            labels.append(label)
            a_pcts.append(pa)
            b_pcts.append(pb)
    st.plotly_chart(
        viz.compare_dumbbell(labels, a_pcts, b_pcts, a_name, b_name),
        config=viz.PLOTLY_CONFIG,
        width="stretch",
    )


def render() -> None:
    season = st.session_state.get(seasons.SEASON_KEY) or seasons.latest_season()

    st.markdown(f"## Advanced &nbsp;{T.chip(season)}", unsafe_allow_html=True)

    stats = _season_stats(season)
    if stats is None:
        return
    view, qualified, min_minutes, show_all = _filters(stats)
    has_official = bool(stats["has_official_advanced"].any())
    _table(view, qualified, min_minutes, show_all, has_official)
    _leaders(qualified, min_minutes, has_official)
    if not _profile(stats, view, qualified):
        return
    _compare(qualified)
