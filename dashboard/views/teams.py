"""Teams - full standings with form, plus per-team detail view."""

import streamlit as st

from dashboard.lib import db
from dashboard.lib import theme as T
from dashboard.lib import viz


def form_dots(form: str) -> str:
    return "".join(
        f'<span class="dot dot-{"w" if ch == "W" else "l"}"></span>'
        for ch in reversed(form)  # oldest to newest, newest dot last
    )


def standings_table(df) -> str:
    head = ('<table class="bip-table"><tr><th class="lft">#</th><th class="lft">Team</th>'
            "<th>W</th><th>L</th><th>PCT</th><th>PTS</th><th>OPP</th><th>+/-</th>"
            '<th style="text-align:left;padding-left:.8rem">Form</th></tr>')
    rows = []
    for i, r in enumerate(df.itertuples(), 1):
        diff_cls = "pos" if r.net > 0 else ("neg" if r.net < 0 else "")
        rows.append(
            f'<tr><td class="lft">{i}</td>'
            f'<td class="lft tm">{T.team_dot(r.team)}{r.team_name}</td>'
            f"<td>{r.w}</td><td>{r.l}</td><td>{r.pct:.3f}</td>"
            f"<td>{r.ppg:.1f}</td><td>{r.opp_ppg:.1f}</td>"
            f'<td class="{diff_cls}">{r.net:+.1f}</td>'
            f'<td style="text-align:left;padding-left:.8rem">{form_dots(r.form)}</td></tr>'
        )
    return head + "".join(rows) + "</table>"


def render() -> None:
    season = st.session_state.get("season") or db.latest_season()
    st.markdown(
        f'## Teams &nbsp;{T.chip(season)}',
        unsafe_allow_html=True,
    )
    standings = db.standings(season)

    tab_east, tab_west, tab_all = st.tabs(["Eastern", "Western", "League"])
    with tab_east:
        st.markdown(f'<div class="bip-card">{standings_table(standings[standings.conf == "East"])}</div>',
                    unsafe_allow_html=True)
    with tab_west:
        st.markdown(f'<div class="bip-card">{standings_table(standings[standings.conf == "West"])}</div>',
                    unsafe_allow_html=True)
    with tab_all:
        st.markdown(f'<div class="bip-card">{standings_table(standings)}</div>',
                    unsafe_allow_html=True)
    st.caption("Form shows the last five games, most recent on the right.")

    st.markdown("#### Team detail")
    pick = st.selectbox("Team", standings["team_name"], label_visibility="collapsed")
    row = standings[standings.team_name == pick].iloc[0]
    games = db.team_game_log(int(row.team_id), season)

    tc = T.team_color(row.team)
    st.markdown(
        f'### {T.team_dot(row.team, 14)}{row.team_name} &nbsp;'
        f'{T.chip(f"{row.w}-{row.l} &middot; {row.conf}", tc)}',
        unsafe_allow_html=True,
    )

    home = games[~games.is_away_game]
    away = games[games.is_away_game]
    t1, t2, t3, t4, t5 = st.columns(5)
    t1.markdown(T.kpi("Points / game", f"{row.ppg:.1f}"), unsafe_allow_html=True)
    t2.markdown(T.kpi("Opp points / game", f"{row.opp_ppg:.1f}"), unsafe_allow_html=True)
    t3.markdown(T.kpi("Net / game", f"{row.net:+.1f}"), unsafe_allow_html=True)
    t4.markdown(T.kpi("Home", f"{int(home.is_win.sum())}-{int((~home.is_win).sum())}"),
                unsafe_allow_html=True)
    t5.markdown(T.kpi("Away", f"{int(away.is_win.sum())}-{int((~away.is_win).sum())}"),
                unsafe_allow_html=True)

    st.markdown("**Game margins** - every game, win margin above the line, loss below")
    st.plotly_chart(viz.team_margins(games), config=viz.PLOTLY_CONFIG,
                    width="stretch")

    st.markdown("**Top contributors**")
    roster = db.player_season_stats(season, min_games=10)
    roster = roster[roster.team == row.team].sort_values("ppg", ascending=False).head(8)
    st.dataframe(
        roster[["player", "gp", "mpg", "ppg", "rpg", "apg", "fg_pct", "plus_minus"]],
        hide_index=True,
        column_config={
            "player": st.column_config.TextColumn("Player", width="medium"),
            "gp": "GP", "mpg": st.column_config.NumberColumn("MIN", format="%.1f"),
            "ppg": st.column_config.NumberColumn("PTS", format="%.1f"),
            "rpg": st.column_config.NumberColumn("REB", format="%.1f"),
            "apg": st.column_config.NumberColumn("AST", format="%.1f"),
            "fg_pct": st.column_config.NumberColumn("FG%", format="%.1f"),
            "plus_minus": st.column_config.NumberColumn("+/-", format="%.1f"),
        },
    )
