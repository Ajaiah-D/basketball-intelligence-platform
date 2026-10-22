"""Teams - one team in depth (ratings with league ranks, the Four Factors,
record splits, margins and its roster), with full standings in their own tab
so the table doesn't crowd out the team view."""

import pandas as pd
import streamlit as st

from dashboard.lib import glossary, payroll, viz
from dashboard.lib import team_metrics as tm
from dashboard.lib import theme as T
from dashboard.lib.data import advanced, finances, players, seasons
from dashboard.lib.data import teams as team_data


def form_dots(form: str) -> str:
    return "".join(
        f'<span class="dot dot-{"w" if ch == "W" else "l"}"></span>'
        for ch in reversed(form)  # oldest to newest, newest dot last
    )


def standings_table(df) -> str:
    def th(label: str, term: str) -> str:
        return f"{label}{T.tip(glossary.TERMS[term])}"

    head = (
        '<table class="bip-table"><tr><th class="lft">#</th><th class="lft">Team</th>'
        f"<th>W</th><th>L</th><th>{th('PCT', 'PCT')}</th><th>PTS</th>"
        f"<th>{th('OPP', 'OPP')}</th><th>{th('+/-', 'Team +/-')}</th>"
        '<th style="text-align:left;padding-left:.8rem">'
        f"{th('Form', 'Form')}</th></tr>"
    )
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


# Every table on the Team tab is the same grid component, at the same row
# height as the Players and Advanced grids.
ROW_HEIGHT = 38
CHART_HEIGHT = 360


def section(title: str, help: str = "") -> None:
    """The one heading style on this tab."""
    st.markdown(f"#### {title}{T.tip(help) if help else ''}", unsafe_allow_html=True)


def _rank_sub(rank) -> str:
    return f"{payroll.ordinal(rank[0])} of {rank[1]}" if rank else ""


def _payroll_card(season: str, team: str) -> tuple[str, str] | None:
    """(value, sub-line) for the Payroll card, or None when the warehouse has
    no reliable salary figure for this team-season (before 1984-85, a source
    gap, or a new season the salary scrape hasn't reached yet)."""
    if not finances.team_finances_available():
        return None
    league = finances.team_payroll_history()
    league = league[league["season"] == season]
    row = league[league["team_abbreviation"] == team]
    if row.empty:
        return None
    label, _ = payroll.bracket(row.iloc[0])
    if label == "Data incomplete":
        return None
    rank = payroll.league_rank(league, team)
    sub = f"{_rank_sub(rank)} &middot; {label.lower()}" if rank else label.lower()
    return payroll.money(row.iloc[0]["team_payroll"]), sub


def _cards(items: list[tuple]) -> None:
    """One row of six equal cards: (label, value, sub, note, help)."""
    cols = st.columns(6)
    # Fewer than six items leave the trailing columns empty, so not strict=True.
    for col, (label, value, sub, note, help) in zip(cols, items, strict=False):
        col.markdown(T.kpi(label, value, sub, note=note, help=help), unsafe_allow_html=True)


def render() -> None:
    season = st.session_state.get("season") or seasons.latest_season()
    st.markdown(f"## Teams &nbsp;{T.chip(season)}", unsafe_allow_html=True)
    standings = team_data.standings(season)

    tab_team, tab_standings = st.tabs(["Team", "Standings"])
    with tab_standings:
        conf = (
            st.segmented_control(
                "Conference",
                ["Eastern", "Western", "League"],
                default="Eastern",
                label_visibility="collapsed",
                key="standings_conf",
            )
            or "Eastern"
        )
        shown = {
            "Eastern": standings[standings.conf == "East"],
            "Western": standings[standings.conf == "West"],
            "League": standings,
        }[conf]
        st.markdown(f'<div class="bip-card">{standings_table(shown)}</div>', unsafe_allow_html=True)
        st.caption("Form shows the last five games, most recent on the right.")
    with tab_team:
        _render_team(season, standings)


def _render_team(season: str, standings: pd.DataFrame) -> None:
    pick: str | None = st.selectbox("Team", standings["team_name"], label_visibility="collapsed")
    row = standings[standings.team_name == pick].iloc[0]
    games = team_data.team_game_log(int(row.team_id), season)

    conf_table = standings[standings.conf == row.conf].reset_index(drop=True)
    seed = int(conf_table.index[conf_table.team == row.team][0]) + 1
    st.markdown(f"### {T.team_dot(row.team, 14)}{row.team_name}", unsafe_allow_html=True)

    # --- Ratings: record, efficiency with league ranks, payroll ------------------
    # The efficiency cards need mart_team_season; an older warehouse without
    # it falls back to per-game scoring from the standings row. (Standings
    # themselves need mart_team_standings, which every published warehouse
    # has.)
    adv = advanced.team_advanced(season) if advanced.marts_available() else pd.DataFrame()
    match = adv[adv.team_id == row.team_id] if not adv.empty else adv
    a = (
        match.iloc[0]
        if len(match) and match.iloc[0].offensive_rating == match.iloc[0].offensive_rating
        else None
    )

    cards = [("Record", f"{row.w}-{row.l}", f"{payroll.ordinal(seed)} in the {row.conf}", "", "")]
    if a is not None:
        for label, field, high, fmt in [
            ("Net rating", "net_rating", True, "{:+.1f}"),
            ("Offensive rating", "offensive_rating", True, "{:.1f}"),
            ("Defensive rating", "defensive_rating", False, "{:.1f}"),
            ("Pace", "pace", True, "{:.1f}"),
        ]:
            rank = tm.league_rank(adv, row.team, field, high)
            cards.append((label, fmt.format(a[field]), _rank_sub(rank), "", glossary.TERMS[label]))
    else:
        cards += [
            ("Points / game", f"{row.ppg:.1f}", "", "", ""),
            ("Opp points / game", f"{row.opp_ppg:.1f}", "", "", ""),
            ("Net / game", f"{row.net:+.1f}", "", "", glossary.TERMS["Net / game"]),
        ]
    pay = _payroll_card(season, row.team)
    if pay:
        cards.append(("Payroll", pay[0], pay[1], "", ""))
    _cards(cards)

    # --- Splits and form -------------------------------------------------------------
    if len(games):
        sp = tm.splits(games, standings)
        section("Splits and form")
        _cards(
            [
                ("Home", sp["home"], "", "", ""),
                ("Away", sp["away"], "", "", ""),
                ("Last 10", sp["last10"], "", "", ""),
                ("Streak", sp["streak"], "", "", ""),
                ("Close games", sp["close"], "", "&le;5 pts", ""),
                ("Vs .500+ teams", sp["vs_winning"], "", "", ""),
            ]
        )

    # --- Four Factors --------------------------------------------------------------------
    if a is not None and "effective_fg_pct" in adv and a.effective_fg_pct == a.effective_fg_pct:
        section("Four Factors", glossary.TERMS["Four Factors"])
        ff = tm.four_factors(adv, row.team)
        pct = "%.1f"
        st.dataframe(
            ff,
            hide_index=True,
            width="stretch",
            row_height=ROW_HEIGHT,
            column_order=[
                "factor",
                "offense",
                "league_offense",
                "offense_rank",
                "defense",
                "league_defense",
                "defense_rank",
            ],
            column_config={
                "factor": st.column_config.TextColumn("Factor"),
                "offense": st.column_config.NumberColumn(
                    "Offense", help="This team's own value", format=pct
                ),
                "league_offense": st.column_config.NumberColumn("League avg", format=pct),
                "offense_rank": st.column_config.TextColumn(
                    "Off. rank", help="1st is the best offense in the league"
                ),
                "defense": st.column_config.NumberColumn(
                    "Defense", help="What opponents managed against this team", format=pct
                ),
                "league_defense": st.column_config.NumberColumn("League avg", format=pct),
                "defense_rank": st.column_config.TextColumn(
                    "Def. rank", help="1st is the best defense in the league"
                ),
            },
        )

    # --- Charts ------------------------------------------------------------------------------
    left, right = st.columns(2)
    if len(games):
        with left:
            section("Game margins")
            fig = viz.team_margins(games)
            fig.update_layout(height=CHART_HEIGHT)
            st.plotly_chart(fig, config=viz.PLOTLY_CONFIG, width="stretch")
    if a is not None:
        with right:
            section("Offense vs defense")
            fig = viz.rating_quadrant(adv, highlight=row.team)
            fig.update_layout(height=CHART_HEIGHT)
            st.plotly_chart(fig, config=viz.PLOTLY_CONFIG, width="stretch")

    # --- Roster ------------------------------------------------------------------------------
    section("Roster")
    roster = players.team_roster(season, row.team, min_games=5)
    roster["note"] = [tm.move_note(p, row.team) for p in roster["team_label"]]
    roster = roster.sort_values("ppg", ascending=False).head(10)
    st.dataframe(
        roster[["player", "note", "gp", "mpg", "ppg", "rpg", "apg", "fg_pct", "plus_minus"]],
        hide_index=True,
        width="stretch",
        row_height=ROW_HEIGHT,
        # Tall enough for every row plus the header, so nothing scrolls.
        height=(len(roster) + 1) * ROW_HEIGHT + 3,
        column_config={
            "player": st.column_config.TextColumn("Player", width="medium"),
            "note": st.column_config.TextColumn(
                "Moved", help="Traded or signed mid-season: where he came from or went"
            ),
            "gp": st.column_config.NumberColumn(**glossary.described("GP")),
            "mpg": st.column_config.NumberColumn(**glossary.described("MIN"), format="%.1f"),
            "ppg": st.column_config.NumberColumn("PTS", format="%.1f"),
            "rpg": st.column_config.NumberColumn("REB", format="%.1f"),
            "apg": st.column_config.NumberColumn("AST", format="%.1f"),
            "fg_pct": st.column_config.NumberColumn(**glossary.described("FG%"), format="%.1f"),
            "plus_minus": st.column_config.NumberColumn(**glossary.marked("+/-"), format="%.1f"),
        },
    )

    # One footnote for the whole tab instead of a caption under every block.
    notes = [
        "Ranks are out of every team that season, 1st = best (fewest points "
        "allowed for defensive rating, fastest for pace)."
    ]
    if a is not None:
        notes.append(f"Ratings are {a.ratings_source}.")
    notes.append(
        "The roster counts only games played for this team, so a player traded "
        "mid-season shows each stint on its own team (minimum 5 games). "
        "Payroll detail is on the Finances page."
    )
    st.caption(" ".join(notes))
