"""Teams - one team in depth (ratings with league ranks, the Four Factors,
record splits, margins and its roster), with full standings in their own tab
so the table doesn't crowd out the team view."""

import pandas as pd
import streamlit as st

from dashboard.lib import db, glossary, payroll
from dashboard.lib import team_metrics as tm
from dashboard.lib import theme as T
from dashboard.lib import viz


def form_dots(form: str) -> str:
    return "".join(
        f'<span class="dot dot-{"w" if ch == "W" else "l"}"></span>'
        for ch in reversed(form)  # oldest to newest, newest dot last
    )


def standings_table(df) -> str:
    def th(label: str, term: str) -> str:
        return f"{label}{T.tip(glossary.TERMS[term])}"

    head = ('<table class="bip-table"><tr><th class="lft">#</th><th class="lft">Team</th>'
            f"<th>W</th><th>L</th><th>{th('PCT', 'PCT')}</th><th>PTS</th>"
            f"<th>{th('OPP', 'OPP')}</th><th>{th('+/-', 'Team +/-')}</th>"
            '<th style="text-align:left;padding-left:.8rem">'
            f'{th("Form", "Form")}</th></tr>')
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


def four_factors_table(ff: pd.DataFrame) -> str:
    """Offense and defense side by side, each with the league average and rank."""
    def fmt(v) -> str:
        return "-" if v is None or v != v else f"{v:.1f}"

    head = ('<table class="bip-table"><tr><th class="lft">Factor</th>'
            "<th>Offense</th><th>League</th><th>Rank</th>"
            "<th>Defense</th><th>League</th><th>Rank</th></tr>")
    rows = [
        f'<tr><td class="lft tm">{r.factor}{T.tip(glossary.TERMS[r.factor])}</td>'
        f"<td>{fmt(r.offense)}</td><td>{fmt(r.league_offense)}</td><td>{r.offense_rank}</td>"
        f"<td>{fmt(r.defense)}</td><td>{fmt(r.league_defense)}</td><td>{r.defense_rank}</td></tr>"
        for r in ff.itertuples()
    ]
    return head + "".join(rows) + "</table>"


def _rank_sub(rank) -> str:
    return f"{payroll.ordinal(rank[0])} of {rank[1]}" if rank else ""


def _payroll_line(season: str, team: str) -> str | None:
    """One sentence on the team's payroll that season, or None when the
    warehouse has no salary data for it (before 1984-85, or a new season the
    salary scrape hasn't reached yet)."""
    if not db.team_finances_available():
        return None
    league = db.team_payroll_history()
    league = league[league["season"] == season]
    row = league[league["team_abbreviation"] == team]
    if row.empty:
        return None
    r = row.iloc[0]
    label, _ = payroll.bracket(r)
    if label == "Data incomplete":
        return None
    rank = payroll.league_rank(league, team)
    rank_text = f", {payroll.ordinal(rank[0])} of {rank[1]}" if rank else ""
    return (f"Payroll {payroll.money(r['team_payroll'])}{rank_text} - "
            f"{label.lower()}. [Full breakdown on Finances](finances)")


def render() -> None:
    season = st.session_state.get("season") or db.latest_season()
    st.markdown(f'## Teams &nbsp;{T.chip(season)}', unsafe_allow_html=True)
    standings = db.standings(season)

    tab_team, tab_standings = st.tabs(["Team", "Standings"])
    with tab_standings:
        conf = st.segmented_control("Conference", ["Eastern", "Western", "League"],
                                    default="Eastern", label_visibility="collapsed",
                                    key="standings_conf") or "Eastern"
        shown = {"Eastern": standings[standings.conf == "East"],
                 "Western": standings[standings.conf == "West"],
                 "League": standings}[conf]
        st.markdown(f'<div class="bip-card">{standings_table(shown)}</div>',
                    unsafe_allow_html=True)
        st.caption("Form shows the last five games, most recent on the right.")
    with tab_team:
        _render_team(season, standings)


def _render_team(season: str, standings: pd.DataFrame) -> None:
    pick = st.selectbox("Team", standings["team_name"], label_visibility="collapsed")
    row = standings[standings.team_name == pick].iloc[0]
    games = db.team_game_log(int(row.team_id), season)

    conf_table = standings[standings.conf == row.conf].reset_index(drop=True)
    seed = int(conf_table.index[conf_table.team == row.team][0]) + 1
    seed_text = f"{payroll.ordinal(seed)} in the {row.conf}"

    tc = T.team_color(row.team)
    st.markdown(
        f'### {T.team_dot(row.team, 14)}{row.team_name} &nbsp;'
        f'{T.chip(f"{row.w}-{row.l} &middot; {seed_text}", tc)}',
        unsafe_allow_html=True,
    )

    # --- Ratings with league ranks --------------------------------------------
    # The efficiency block is additive; a warehouse without the marts falls
    # back to per-game scoring, which every published warehouse has.
    adv = db.team_advanced(season) if db.marts_available() else pd.DataFrame()
    a = adv[adv.team_id == row.team_id].iloc[0] if not adv.empty and \
        (adv.team_id == row.team_id).any() else None
    c = st.columns(5)
    c[0].markdown(T.kpi("Record", f"{row.w}-{row.l}", seed_text,
                        help=glossary.TERMS["Seed"]), unsafe_allow_html=True)
    if a is not None and a.offensive_rating == a.offensive_rating:
        for col, label, field, high, fmt in [
            (c[1], "Net rating", "net_rating", True, "{:+.1f}"),
            (c[2], "Offensive rating", "offensive_rating", True, "{:.1f}"),
            (c[3], "Defensive rating", "defensive_rating", False, "{:.1f}"),
            (c[4], "Pace", "pace", True, "{:.1f}"),
        ]:
            rank = tm.league_rank(adv, row.team, field, high)
            col.markdown(T.kpi(label, fmt.format(a[field]), _rank_sub(rank),
                               help=glossary.TERMS[label]), unsafe_allow_html=True)
    else:
        c[1].markdown(T.kpi("Points / game", f"{row.ppg:.1f}"), unsafe_allow_html=True)
        c[2].markdown(T.kpi("Opp points / game", f"{row.opp_ppg:.1f}"), unsafe_allow_html=True)
        c[3].markdown(T.kpi("Net / game", f"{row.net:+.1f}",
                            help=glossary.TERMS["Net / game"]), unsafe_allow_html=True)
    st.caption("Ranks are out of every team that season; for defensive rating, "
               "1st means the fewest points allowed. Pace ranks fastest first.")

    line = _payroll_line(season, row.team)
    if line:
        # Escaped: st.markdown reads a pair of dollar signs as a formula.
        st.markdown(line.replace("$", "\\$"))

    # --- Four Factors -----------------------------------------------------------
    if a is not None and "effective_fg_pct" in adv and a.effective_fg_pct == a.effective_fg_pct:
        st.markdown(f'#### Four Factors{T.tip(glossary.TERMS["Four Factors"])}',
                    unsafe_allow_html=True)
        st.markdown(f'<div class="bip-card">{four_factors_table(tm.four_factors(adv, row.team))}</div>',
                    unsafe_allow_html=True)
        st.caption("Percentages. Rank 1st is the best in the league on that end - "
                   "for defense, that means holding opponents lowest (or forcing "
                   "the most turnovers).")

    # --- Splits and form ----------------------------------------------------------
    if len(games):
        st.markdown("#### Splits and form")
        sp = tm.splits(games, standings)
        s = st.columns(6)
        for col, label, value, term in [
            (s[0], "Home", sp["home"], None),
            (s[1], "Away", sp["away"], None),
            (s[2], "Last 10", sp["last10"], None),
            (s[3], "Streak", sp["streak"], None),
            (s[4], "Close games", sp["close"], "Close-game record"),
            (s[5], "Vs winning teams", sp["vs_winning"], "Vs winning teams"),
        ]:
            col.markdown(T.kpi(label, value, help=glossary.TERMS[term] if term else ""),
                         unsafe_allow_html=True)

        st.markdown("**Game margins** - every game, win margin above the line, loss below")
        st.plotly_chart(viz.team_margins(games), config=viz.PLOTLY_CONFIG, width="stretch")

    if a is not None and a.offensive_rating == a.offensive_rating:
        st.markdown("**Offense vs defense** - every team, up and to the right is better")
        st.plotly_chart(viz.rating_quadrant(adv, highlight=row.team),
                        config=viz.PLOTLY_CONFIG, width="stretch")
        st.caption(f"Lines mark the league average. Ratings for {season} are "
                   f"{a.ratings_source}.")

    # --- Roster -------------------------------------------------------------------
    st.markdown("#### Top contributors")
    roster = db.team_roster(season, row.team, min_games=5)
    paths = db.player_team_paths(season)
    roster = roster.merge(paths[["player_id", "team_path"]], on="player_id", how="left")
    roster["note"] = [tm.move_note(p, row.team) for p in roster["team_path"]]
    roster = roster.sort_values("ppg", ascending=False).head(10)
    st.dataframe(
        roster[["player", "note", "gp", "mpg", "ppg", "rpg", "apg", "fg_pct", "plus_minus"]],
        hide_index=True,
        column_config={
            "player": st.column_config.TextColumn("Player", width="medium"),
            "note": st.column_config.TextColumn(
                "Moved", help="Traded or signed mid-season: where he came from or went"),
            "gp": st.column_config.NumberColumn(**glossary.described("GP")),
            "mpg": st.column_config.NumberColumn(**glossary.described("MIN"), format="%.1f"),
            "ppg": st.column_config.NumberColumn("PTS", format="%.1f"),
            "rpg": st.column_config.NumberColumn("REB", format="%.1f"),
            "apg": st.column_config.NumberColumn("AST", format="%.1f"),
            "fg_pct": st.column_config.NumberColumn(**glossary.described("FG%"), format="%.1f"),
            "plus_minus": st.column_config.NumberColumn(**glossary.marked("+/-"), format="%.1f"),
        },
    )
    st.caption("Only games played for this team count, so a player traded mid-season "
               "shows each stint on its own team. Minimum 5 games with the team.")
