"""Players - searchable stats table + per-player detail view.

Scope toggle: one season, or Career (every ingested season pooled - the
percentages are recomputed from summed makes/attempts, not averaged).
Every percentage is shown next to its attempt volume so low-volume
outliers (a center shooting 100% on three 3PA) are visible at a glance.
"""

import streamlit as st

from dashboard.lib import db, media
from dashboard.lib import theme as T
from dashboard.lib import viz

TABLE_COLS = ["player", "team", "gp", "mpg", "ppg", "rpg", "apg", "spg", "bpg",
              "fg_pct", "fga_pg", "tpg", "tpa_pg", "fg3_pct", "ft_pct", "fta_pg",
              "ts_pct", "plus_minus"]

TREND_STATS = {"PPG": "ppg", "RPG": "rpg", "APG": "apg", "3PM/g": "tpg"}


def render() -> None:
    season = st.session_state.get("season") or db.latest_season()

    head = st.container()  # title renders here once the scope toggle is known
    f0, f1, f2, f3 = st.columns([2, 2, 2, 3])
    scope = f0.segmented_control("Scope", ["Season", "Career"], default="Season",
                                 label_visibility="collapsed") or "Season"
    career = scope == "Career"

    if career:
        stats = db.player_career_stats()
        stats["span"] = stats["first_season"].where(
            stats["seasons"] == 1,
            stats["first_season"] + " to " + stats["last_season"])
        min_gp = f2.slider("Min career games", 1, 1500, 200)
    else:
        stats = db.player_season_stats(season)
        min_gp = f2.slider("Min games", 1, 82, 25)

    with head:
        st.markdown(
            f'## Players &nbsp;'
            f'{T.chip("All seasons &middot; career totals" if career else season)}',
            unsafe_allow_html=True,
        )

    teams = ["All teams"] + sorted(stats["team"].unique())
    team = f1.selectbox("Team", teams, label_visibility="collapsed",
                        help="Career scope: a player's most recent team")
    search = f3.text_input("Search", placeholder="Search players...",
                           label_visibility="collapsed")

    view = stats[stats.gp >= min_gp]
    if team != "All teams":
        view = view[view.team == team]
    if search:
        view = view[view.player.str.contains(search, case=False, na=False)]
    view = view.sort_values("ppg", ascending=False)

    table_cols = TABLE_COLS.copy()
    if career:
        table_cols[2:2] = ["seasons", "span"]

    st.dataframe(
        view[table_cols],
        hide_index=True,
        height=430,
        column_config={
            "player": st.column_config.TextColumn("Player", width="medium"),
            "team": st.column_config.TextColumn("Team", width="small"),
            "seasons": st.column_config.NumberColumn("Yrs"),
            "span": st.column_config.TextColumn("Span", width="medium"),
            "gp": st.column_config.NumberColumn("GP"),
            "mpg": st.column_config.NumberColumn("MIN", format="%.1f"),
            "ppg": st.column_config.NumberColumn("PTS", format="%.1f"),
            "rpg": st.column_config.NumberColumn("REB", format="%.1f"),
            "apg": st.column_config.NumberColumn("AST", format="%.1f"),
            "spg": st.column_config.NumberColumn("STL", format="%.1f"),
            "bpg": st.column_config.NumberColumn("BLK", format="%.1f"),
            "fg_pct": st.column_config.NumberColumn("FG%", format="%.1f"),
            "fga_pg": st.column_config.NumberColumn("FGA", format="%.1f",
                                                    help="Field goal attempts per game"),
            "tpg": st.column_config.NumberColumn("3PM", format="%.1f"),
            "tpa_pg": st.column_config.NumberColumn("3PA", format="%.1f",
                                                    help="Three-point attempts per game"),
            "fg3_pct": st.column_config.NumberColumn("3P%", format="%.1f"),
            "ft_pct": st.column_config.NumberColumn("FT%", format="%.1f"),
            "fta_pg": st.column_config.NumberColumn("FTA", format="%.1f",
                                                    help="Free throw attempts per game"),
            "ts_pct": st.column_config.NumberColumn("TS%", format="%.1f",
                                                    help="True shooting: pts / (2 x (FGA + 0.44 x FTA))"),
            "plus_minus": st.column_config.NumberColumn("+/-", format="%.1f"),
        },
    )
    if career:
        st.caption("Career view pools every ingested season (1979-80 onward) - "
                   "the sidebar season selector does not apply here. Percentages "
                   "are computed from career totals, shown next to attempt volume.")
    else:
        st.caption("Click a column header to sort. Per-game averages; percentages are "
                   "season totals, shown next to their attempt volume (FGA / 3PA / FTA).")

    st.markdown("#### Player detail")
    options = view if len(view) else stats
    pick = st.selectbox(
        "Player", options.sort_values("ppg", ascending=False)["player"],
        label_visibility="collapsed",
    )
    if not pick:
        return
    row = stats[stats.player == pick].iloc[0]

    tc = T.team_color(row.team)
    chip_text = (f"{row.team} &middot; {row.seasons} seasons &middot; {row.gp} GP"
                 if career else
                 f"{row.team} &middot; {row.gp} GP &middot; {row.mpg:.1f} MPG")
    st.markdown(
        f'<div style="display:flex;align-items:center;gap:14px;margin:.4rem 0 .8rem 0">'
        f'{media.avatar_html(int(row.player_id), row.player, size=84, ring=tc)}'
        f'<div><span style="font-size:1.6rem;font-weight:800;letter-spacing:-.02em">'
        f'{row.player}</span><br>'
        f'{T.chip(chip_text, tc)}'
        f'</div></div>',
        unsafe_allow_html=True,
    )
    tiles = st.columns(6)

    def fmt(v, suffix=""):
        return f"{v:.1f}{suffix}" if v == v else "-"

    for col, (label, val, sub) in zip(tiles, [
        ("PPG", fmt(row.ppg), f"{row.pts_total:,} career pts" if career else ""),
        ("RPG", fmt(row.rpg), ""),
        ("APG", fmt(row.apg), ""),
        ("FG%", fmt(row.fg_pct), f"on {fmt(row.fga_pg)} FGA/g"),
        ("3P%", fmt(row.fg3_pct), f"on {fmt(row.tpa_pg)} 3PA/g ({row.tpa_total} total)"),
        ("TS%", fmt(row.ts_pct), "true shooting"),
    ]):
        col.markdown(T.kpi(label, val, sub), unsafe_allow_html=True)

    if row.tpa_total and row.tpa_total < 50 and row.fg3_pct == row.fg3_pct:
        when = "across a whole career" if career else "all season"
        st.caption(f"Note: {row.player}'s 3P% comes from only {row.tpa_total} "
                   f"attempts {when} - treat it as noise, not a skill signal.")

    if career:
        bk = db.player_season_breakdown(int(row.player_id))
        st.markdown("**Career trajectory** - bars are season averages, "
                    "the line is the career average to date")
        stat_label = st.segmented_control(
            "Stat", list(TREND_STATS), default="PPG",
            label_visibility="collapsed") or "PPG"
        st.plotly_chart(viz.career_trend(bk, TREND_STATS[stat_label], stat_label),
                        config=viz.PLOTLY_CONFIG, width="stretch")

        s1, s2, s3, s4 = st.columns(4)
        s1.markdown(T.kpi("Career high", f"{row.career_high}", "points in a game"),
                    unsafe_allow_html=True)
        s2.markdown(T.kpi("Seasons", f"{row.seasons}", row.span),
                    unsafe_allow_html=True)
        s3.markdown(T.kpi("Total points", f"{row.pts_total:,}"),
                    unsafe_allow_html=True)
        s4.markdown(T.kpi("Record in games",
                          f"{row.wins}-{row.gp - row.wins}"),
                    unsafe_allow_html=True)
        return

    games = db.player_game_log(int(row.player_id), season)
    c1, c2 = st.columns([3, 2])
    with c1:
        st.markdown("**Scoring trend**")
        st.plotly_chart(viz.player_trend(games), config=viz.PLOTLY_CONFIG,
                        width="stretch")
    with c2:
        st.markdown("**Shooting vs league** (labels show attempts/game)")
        st.plotly_chart(
            viz.shooting_profile(row, db.league_shooting_averages(season), row.player),
            config=viz.PLOTLY_CONFIG, width="stretch")

    home = games[~games.is_away_game]
    away = games[games.is_away_game]
    s1, s2, s3, s4 = st.columns(4)
    s1.markdown(T.kpi("Home PPG", f"{home.points.mean():.1f}" if len(home) else "-"),
                unsafe_allow_html=True)
    s2.markdown(T.kpi("Away PPG", f"{away.points.mean():.1f}" if len(away) else "-"),
                unsafe_allow_html=True)
    s3.markdown(T.kpi("Season high", f"{games.points.max():.0f}"), unsafe_allow_html=True)
    s4.markdown(T.kpi("Record in games", f"{int(games.is_win.sum())}-{int((~games.is_win).sum())}"),
                unsafe_allow_html=True)
