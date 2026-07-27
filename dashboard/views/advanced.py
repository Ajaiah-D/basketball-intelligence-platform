"""Advanced - rate metrics, leaderboards and a two-player comparison.

Deliberately narrow: one table with a curated column set, a leaderboard
strip, and a head-to-head. The full metric list stays behind a toggle so
the default view is readable rather than exhaustive.

Rate stats need a minutes floor to mean anything (one made three-pointer
on the season is a 150% true shooting percentage), so every view here is
gated on minutes played rather than showing the whole league.
"""

import streamlit as st

from dashboard.lib import db, media
from dashboard.lib import theme as T
from dashboard.lib import viz

# The default table: enough to answer "who is efficient and how involved
# were they" without becoming a spreadsheet.
CORE_COLS = ["player_name", "team_abbreviation", "games_played", "minutes_per_game",
             "points_per_game", "true_shooting_pct", "effective_fg_pct",
             "usage_pct", "assist_pct", "rebound_pct", "game_score"]

EXTRA_COLS = ["turnover_pct", "steal_pct", "block_pct", "points_per_36",
              "points_per_100", "net_rating", "player_impact_estimate"]

# Percentile comparison uses metrics that exist for every complete season,
# so the head-to-head still works for pre-1997 players.
COMPARE_METRICS = ["TS%", "USG%", "AST%", "REB%", "STL%", "BLK%", "Game score"]

COLUMN_CONFIG = {
    "player_name": st.column_config.TextColumn("Player", width="medium"),
    "team_abbreviation": st.column_config.TextColumn("Team", width="small"),
    "games_played": st.column_config.NumberColumn("GP"),
    "minutes_per_game": st.column_config.NumberColumn("MIN", format="%.1f"),
    "points_per_game": st.column_config.NumberColumn("PTS", format="%.1f"),
    "true_shooting_pct": st.column_config.NumberColumn(
        "TS%", format="%.1f", help="Points per shooting possession, counts 3s and free throws"),
    "effective_fg_pct": st.column_config.NumberColumn(
        "eFG%", format="%.1f", help="Field goal percentage with 3-pointers weighted 1.5x"),
    "usage_pct": st.column_config.NumberColumn(
        "USG%", format="%.1f", help="Share of team possessions ended while on the floor"),
    "assist_pct": st.column_config.NumberColumn(
        "AST%", format="%.1f", help="Share of teammate field goals assisted"),
    "rebound_pct": st.column_config.NumberColumn(
        "REB%", format="%.1f", help="Share of available rebounds grabbed"),
    "game_score": st.column_config.NumberColumn(
        "GmSc", format="%.1f", help="Hollinger game score, about 10 is an average starter"),
    "turnover_pct": st.column_config.NumberColumn("TOV%", format="%.1f"),
    "steal_pct": st.column_config.NumberColumn("STL%", format="%.1f"),
    "block_pct": st.column_config.NumberColumn("BLK%", format="%.1f"),
    "points_per_36": st.column_config.NumberColumn("P/36", format="%.1f"),
    "points_per_100": st.column_config.NumberColumn("P/100", format="%.1f"),
    "net_rating": st.column_config.NumberColumn(
        "NET", format="%.1f", help="Team net rating with the player on the floor (1996-97 on)"),
    "player_impact_estimate": st.column_config.NumberColumn(
        "PIE", format="%.1f", help="Player impact estimate, official NBA metric (1996-97 on)"),
}


def leader_card(title: str, df, col: str, fmt: str = "{:.1f}") -> str:
    rows = []
    for i, r in enumerate(df.itertuples(), 1):
        rows.append(
            f'<div class="bip-row">{T.rank_badge(i)}'
            f'<span class="bip-name">{r.player_name} '
            f'<span class="bip-team" style="color:{T.team_color(r.team_abbreviation)}">'
            f'{r.team_abbreviation}</span></span>'
            f'<span class="bip-val">{fmt.format(getattr(r, col))}</span></div>'
        )
    return f'<div class="bip-card"><h4>{title}</h4>{"".join(rows)}</div>'


def render() -> None:
    season = st.session_state.get("season") or db.latest_season()
    available = db.advanced_seasons()

    st.markdown(f'## Advanced &nbsp;{T.chip(season)}', unsafe_allow_html=True)

    if season not in available:
        st.info(
            f"Advanced metrics are not available for {season}. The NBA's box "
            "scores are missing rebounds, turnovers and field goal attempts "
            "before 1985-86, and those are the inputs every rate metric needs. "
            f"Pick {available[-1]} or later in the sidebar."
        )
        return

    stats = db.player_advanced(season)
    if stats.empty:
        st.info("No player data for this season yet.")
        return

    # A rate stat on 40 minutes is noise, so the floor scales with how much
    # of the season has been played rather than sitting at a fixed number.
    max_min = int(stats["minutes"].max())
    default_floor = min(500, max(50, int(max_min * 0.3)))
    f1, f2, f3 = st.columns([2, 2, 3])
    min_minutes = f1.slider("Minimum minutes", 0, max(100, max_min),
                            default_floor, step=50)
    show_all = f2.toggle("All metrics", value=False,
                         help="Adds turnover, steal, block and per-100 columns")
    search = f3.text_input("Search", placeholder="Search players...",
                           label_visibility="collapsed")

    view = stats[stats.minutes >= min_minutes]
    qualified = view.copy()  # the pool percentiles are measured against
    if search:
        view = view[view.player_name.str.contains(search, case=False, na=False)]
    view = view.sort_values("game_score", ascending=False, na_position="last")

    cols = CORE_COLS + (EXTRA_COLS if show_all else [])
    st.dataframe(view[cols], hide_index=True, height=400,
                 column_config=COLUMN_CONFIG)

    has_official = bool(stats["has_official_advanced"].any())
    source_note = ("Net rating and PIE are official NBA figures; everything else is "
                   "computed from box scores." if has_official else
                   "All metrics are computed from box scores. The NBA did not publish "
                   "official advanced stats until 1996-97.")
    st.caption(f"{len(qualified)} players with {min_minutes}+ minutes. "
               f"Sorted by game score. {source_note}")

    # --- Leaders ---------------------------------------------------------
    st.markdown("#### Efficiency leaders")
    l1, l2, l3, l4 = st.columns(4)
    l1.markdown(leader_card("True shooting",
                            qualified.nlargest(5, "true_shooting_pct"), "true_shooting_pct"),
                unsafe_allow_html=True)
    l2.markdown(leader_card("Usage", qualified.nlargest(5, "usage_pct"), "usage_pct"),
                unsafe_allow_html=True)
    l3.markdown(leader_card("Game score", qualified.nlargest(5, "game_score"), "game_score"),
                unsafe_allow_html=True)
    if has_official and qualified["player_impact_estimate"].notna().any():
        l4.markdown(leader_card("Impact (PIE)",
                                qualified.nlargest(5, "player_impact_estimate"),
                                "player_impact_estimate"), unsafe_allow_html=True)
    else:
        l4.markdown(leader_card("Rebound rate",
                                qualified.nlargest(5, "rebound_pct"), "rebound_pct"),
                    unsafe_allow_html=True)
    st.caption(f"Among players with {min_minutes}+ minutes.")

    # --- Player profile --------------------------------------------------
    st.markdown("#### Player profile")
    options = view if len(view) else qualified
    pick = st.selectbox("Player", options["player_name"], label_visibility="collapsed")
    if not pick:
        return
    row = qualified[qualified.player_name == pick]
    if row.empty:
        row = stats[stats.player_name == pick]
    row = row.iloc[0]

    tc = T.team_color(row.team_abbreviation)
    st.markdown(
        f'<div style="display:flex;align-items:center;gap:14px;margin:.4rem 0 .8rem 0">'
        f'{media.avatar_html(int(row.player_id), row.player_name, size=72, ring=tc)}'
        f'<div><span style="font-size:1.4rem;font-weight:800;letter-spacing:-.02em">'
        f'{row.player_name}</span><br>'
        f'{T.chip(f"{row.team_abbreviation} &middot; {row.games_played} GP &middot; "
                  f"{row.minutes_per_game:.1f} MPG", tc)}</div></div>',
        unsafe_allow_html=True,
    )

    rows = []
    for label in COMPARE_METRICS:
        col, higher_better, _ = db.ADVANCED_METRICS[label]
        val = row.get(col)
        if val is None or val != val:
            continue
        pct = db.percentile_of(qualified[col], val, higher_better)
        if pct is not None:
            rows.append((label, pct, val))
    st.plotly_chart(viz.percentile_bars(rows), config=viz.PLOTLY_CONFIG,
                    width="stretch")
    st.caption("Bars are percentile rank against the qualified pool; the number in "
               "front is the raw value. TOV% is inverted so longer is always better.")

    # --- Head to head ----------------------------------------------------
    st.markdown("#### Compare two players")
    c1, c2 = st.columns(2)
    names = qualified.sort_values("game_score", ascending=False,
                                  na_position="last")["player_name"].tolist()
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
        col, higher_better, _ = db.ADVANCED_METRICS[label]
        pa = db.percentile_of(qualified[col], a.get(col), higher_better)
        pb = db.percentile_of(qualified[col], b.get(col), higher_better)
        if pa is not None and pb is not None:
            labels.append(label)
            a_pcts.append(pa)
            b_pcts.append(pb)
    st.plotly_chart(
        viz.compare_dumbbell(labels, a_pcts, b_pcts, a_name, b_name),
        config=viz.PLOTLY_CONFIG, width="stretch")
