"""Players - searchable stats table + per-player detail view.

Scope toggle: one season, or Career (every ingested season pooled - the
percentages are recomputed from summed makes/attempts, not averaged).
Every percentage is shown next to its attempt volume so low-volume
outliers (a center shooting 100% on three 3PA) are visible at a glance.

Search in Season scope looks in the selected season first; a player who
didn't play that season is still found, at his most recent season, marked
by a Season column (data.players.player_latest_seasons).
"""

import unicodedata

import pandas as pd
import streamlit as st

from dashboard.lib import glossary, media, viz
from dashboard.lib import theme as T
from dashboard.lib.data import players, seasons
from dashboard.lib.stats import percentile_of

TABLE_COLS = [
    "player",
    "team_label",
    "gp",
    "mpg",
    "ppg",
    "rpg",
    "apg",
    "spg",
    "bpg",
    "fg_pct",
    "fga_pg",
    "tpg",
    "tpa_pg",
    "fg3_pct",
    "ft_pct",
    "fta_pg",
    "ts_pct",
    "plus_minus",
]

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


def _fold(text) -> str:
    """Lower-case, accents dropped, so "jokic" finds "Jokić"."""
    return unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode().lower()


def _sync_season() -> None:
    """The page's season box drives the sidebar's (key "season"), which every
    season-scoped page reads."""
    st.session_state["season"] = st.session_state["players_season"]


def render() -> None:
    season = st.session_state.get("season") or seasons.latest_season()

    head = st.container()  # title renders here once the scope toggle is known
    f0, fs, f1, f2, f3 = st.columns([2, 2, 2, 2, 3])
    scope = (
        f0.segmented_control(
            "Scope", ["Season", "Career"], default="Season", label_visibility="collapsed"
        )
        or "Season"
    )
    career = scope == "Career"

    if career:
        fs.selectbox(
            "Season",
            ["All seasons"],
            disabled=True,
            label_visibility="collapsed",
            key="players_season_all",
        )
    else:
        # Follow the sidebar, so the two boxes always show the same season.
        st.session_state["players_season"] = season
        fs.selectbox(
            "Season",
            seasons.seasons(),
            key="players_season",
            label_visibility="collapsed",
            on_change=_sync_season,
            help="Same as the sidebar's season picker",
        )

    if career:
        stats = players.player_career_stats()
        stats["team_label"] = stats["team"]
        stats["span"] = stats["first_season"].where(
            stats["seasons"] == 1, stats["first_season"] + " to " + stats["last_season"]
        )
        min_gp = f2.slider("Min career games", 1, 1500, 200)
    else:
        stats = players.player_season_stats(season)
        min_gp = f2.slider("Min games", 1, 82, 25)

    with head:
        st.markdown(
            f"## Players &nbsp;"
            f"{T.chip('All seasons &middot; career totals' if career else season)}",
            unsafe_allow_html=True,
        )

    teams = ["All teams", *sorted(stats["team"].unique())]
    team = f1.selectbox(
        "Team",
        teams,
        label_visibility="collapsed",
        help="Career scope: a player's most recent team",
    )
    search = f3.text_input("Search", placeholder="Search players...", label_visibility="collapsed")

    view = stats[stats.gp >= min_gp]
    if team != "All teams":
        # A traded player is listed under every team he played for.
        view = view[view.team_label.str.contains(team, regex=False)]
    if search:
        view = view[view.player.map(_fold).str.contains(_fold(search).strip(), regex=False)]
    view = view.sort_values("ppg", ascending=False)

    # Season scope: a searched player who didn't play this season shows at
    # his most recent season instead, after this season's matches.
    others = pd.DataFrame()
    if search.strip() and not career:
        others = players.player_latest_seasons(search, min_gp)
        others = others[~others.player_id.isin(view.player_id)]
        if team != "All teams":
            others = others[others.team_label.str.contains(team, regex=False)]
        others = others.sort_values("ppg", ascending=False)
    if not career:
        view = view.assign(season=season, pick=view.player)
    if len(others):
        others = others.assign(pick=others.player + " (" + others.season + ")")
        view = pd.concat([view, others], ignore_index=True)

    table_cols = TABLE_COLS.copy()
    if career:
        table_cols[2:2] = ["seasons", "span"]
    elif len(others):
        table_cols[1:1] = ["season"]

    # Scale the PTS bar to the best scorer actually in view, so the column
    # still reads as a comparison after a search or a min-games filter
    # narrows the table. Guarded because an empty search result has no max.
    ppg_max = float(view["ppg"].max()) if len(view) and view["ppg"].notna().any() else 1.0

    st.dataframe(
        view[table_cols],
        hide_index=True,
        height=430,
        row_height=38,
        column_config={
            "player": st.column_config.TextColumn("Player", width="medium"),
            "team_label": st.column_config.TextColumn(
                "Team",
                width="small",
                help="Two teams (CHI → BOS) means traded mid-season; the line covers both",
            ),
            "seasons": st.column_config.NumberColumn("Yrs"),
            "season": st.column_config.TextColumn(
                "Season",
                width="small",
                help="Players who didn't play the selected season show their most recent one",
            ),
            "span": st.column_config.TextColumn("Span", width="medium"),
            "gp": st.column_config.NumberColumn(**glossary.described("GP")),
            "mpg": st.column_config.NumberColumn(**glossary.described("MIN"), format="%.1f"),
            "ppg": st.column_config.ProgressColumn(
                "PTS", format="%.1f", min_value=0, max_value=ppg_max, color=T.ACCENT, width="medium"
            ),
            "rpg": st.column_config.NumberColumn("REB", format="%.1f"),
            "apg": st.column_config.NumberColumn("AST", format="%.1f"),
            "spg": st.column_config.NumberColumn("STL", format="%.1f"),
            "bpg": st.column_config.NumberColumn("BLK", format="%.1f"),
            "fg_pct": st.column_config.NumberColumn(**glossary.described("FG%"), format="%.1f"),
            "fga_pg": st.column_config.NumberColumn(**glossary.described("FGA"), format="%.1f"),
            "tpg": st.column_config.NumberColumn(**glossary.described("3PM"), format="%.1f"),
            "tpa_pg": st.column_config.NumberColumn(**glossary.described("3PA"), format="%.1f"),
            "fg3_pct": st.column_config.NumberColumn(**glossary.described("3P%"), format="%.1f"),
            "ft_pct": st.column_config.NumberColumn(**glossary.described("FT%"), format="%.1f"),
            "fta_pg": st.column_config.NumberColumn(**glossary.described("FTA"), format="%.1f"),
            "ts_pct": st.column_config.NumberColumn(**glossary.marked("TS%"), format="%.1f"),
            "plus_minus": st.column_config.NumberColumn(**glossary.marked("+/-"), format="%.1f"),
        },
    )
    if career:
        st.caption(
            "Career view pools every ingested season (1979-80 onward) - "
            "the sidebar season selector does not apply here. Percentages "
            "are computed from career totals, shown next to attempt volume."
        )
    else:
        if len(others):
            n = len(others)
            st.caption(
                f'{n} player{"s" if n > 1 else ""} matching "{search.strip()}" '
                f"didn't play {season}: shown at their most recent season "
                f"(the Season column), after {season}'s players."
            )
        st.caption(
            "Click a column header to sort. Per-game averages; percentages are "
            "season totals, shown next to their attempt volume (FGA / 3PA / FTA)."
        )

    st.markdown("#### Player detail")
    if career:
        options = (view if len(view) else stats).sort_values("ppg", ascending=False)
        options = options.assign(pick=options.player)
    else:
        options = (
            view
            if len(view)
            else (
                stats.assign(season=season, pick=stats.player).sort_values("ppg", ascending=False)
            )
        )
    pick: str | None = st.selectbox(
        "Player", options["pick"], label_visibility="collapsed", key="players_pick"
    )
    if not pick:
        return
    row = options[options["pick"] == pick].iloc[0]
    # The season this row is from: the selected one, or a searched player's
    # most recent one.
    row_season = season if career else row.season

    tc = T.team_color(row.team)
    chip_text = (
        f"{row.team} &middot; {row.seasons} seasons &middot; {row.gp} GP"
        if career
        else f"{row.team_label} &middot; {row.gp} GP &middot; {row.mpg:.1f} MPG"
        + (f" &middot; {row_season}" if row_season != season else "")
    )
    st.markdown(
        f'<div style="display:flex;align-items:center;gap:14px;margin:.4rem 0 .8rem 0">'
        f"{media.avatar_html(int(row.player_id), row.player, size=84, ring=tc)}"
        f'<div><span style="font-size:1.6rem;font-weight:800;letter-spacing:-.02em">'
        f"{row.player}</span><br>"
        f"{T.chip(chip_text, tc)}"
        f"</div></div>",
        unsafe_allow_html=True,
    )
    tiles = st.columns(6)

    def fmt(v, suffix=""):
        return f"{v:.1f}{suffix}" if v == v else "-"

    for col, (label, val, sub) in zip(
        tiles,
        [
            ("PPG", fmt(row.ppg), f"{row.pts_total:,} career pts" if career else ""),
            ("RPG", fmt(row.rpg), ""),
            ("APG", fmt(row.apg), ""),
            ("FG%", fmt(row.fg_pct), f"on {fmt(row.fga_pg)} FGA/g"),
            ("3P%", fmt(row.fg3_pct), f"on {fmt(row.tpa_pg)} 3PA/g ({row.tpa_total} total)"),
            ("TS%", fmt(row.ts_pct), "true shooting"),
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

    if career:
        bk = players.player_season_breakdown(int(row.player_id))
        st.markdown(
            "**Career trajectory** - bars are season averages, "
            "the line is the career average to date"
        )
        stat_label = (
            st.segmented_control(
                "Stat", list(TREND_STATS), default="PPG", label_visibility="collapsed"
            )
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
        s4.markdown(
            T.kpi("Record in games", f"{row.wins}-{row.gp - row.wins}"), unsafe_allow_html=True
        )
        return

    games = players.player_game_log(int(row.player_id), row_season)
    c1, c2 = st.columns([3, 2])
    with c1:
        st.markdown("**Scoring trend**")
        st.plotly_chart(viz.player_trend(games), config=viz.PLOTLY_CONFIG, width="stretch")
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

    home = games[~games.is_away_game]
    away = games[games.is_away_game]
    s1, s2, s3, s4 = st.columns(4)
    s1.markdown(
        T.kpi("Home PPG", f"{home.points.mean():.1f}" if len(home) else "-"), unsafe_allow_html=True
    )
    s2.markdown(
        T.kpi("Away PPG", f"{away.points.mean():.1f}" if len(away) else "-"), unsafe_allow_html=True
    )
    s3.markdown(T.kpi("Season high", f"{games.points.max():.0f}"), unsafe_allow_html=True)
    s4.markdown(
        T.kpi("Record in games", f"{int(games.is_win.sum())}-{int((~games.is_win).sum())}"),
        unsafe_allow_html=True,
    )
