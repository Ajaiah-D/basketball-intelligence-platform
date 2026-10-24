"""The Team tab: one team in depth (ratings, record splits, where it ranks
in the league on every key stat, its players on each of those areas,
margins and its roster)."""

import pandas as pd
import streamlit as st

from core.fmt import money, ordinal
from dashboard.lib import glossary, payroll, viz
from dashboard.lib import team_metrics as tm
from dashboard.lib import theme as T
from dashboard.lib.data import advanced, finances, players
from dashboard.lib.data import teams as team_data
from dashboard.views.teams.breakdown import render_breakdown
from dashboard.views.teams.common import ROW_HEIGHT, section
from dashboard.views.teams.profile import render_profile
from dashboard.views.teams.scatter import render_scatter

CHART_HEIGHT = 360


def _rank_sub(rank: tuple[int, int] | None) -> str:
    return f"{ordinal(rank[0])} of {rank[1]}" if rank else ""


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
    return money(row.iloc[0]["team_payroll"]), sub


def _cards(items: list[tuple]) -> None:
    """One row of six equal cards: (label, value, sub, note, help)."""
    cols = st.columns(6)
    # Fewer than six items leave the trailing columns empty, so not strict=True.
    for col, (label, value, sub, note, help) in zip(cols, items, strict=False):
        col.markdown(T.kpi(label, value, sub, note=note, help=help), unsafe_allow_html=True)


def _ratings(
    season: str, row: pd.Series, seed: int, adv: pd.DataFrame, a: pd.Series | None
) -> None:
    """Record, efficiency with league ranks, payroll."""
    cards = [("Record", f"{row.w}-{row.l}", f"{ordinal(seed)} in the {row.conf}", "", "")]
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


def _splits(games: pd.DataFrame, standings: pd.DataFrame) -> None:
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


def _charts(
    games: pd.DataFrame,
    standings: pd.DataFrame,
    adv: pd.DataFrame,
    season: str,
    team: str,
    has_ratings: bool,
) -> None:
    left, right = st.columns(2)
    if len(games):
        with left:
            section("Game margins")
            fig = viz.team_margins(games)
            fig.update_layout(height=CHART_HEIGHT)
            st.plotly_chart(fig, config=viz.PLOTLY_CONFIG, width="stretch")
    with right:
        render_scatter(season, team, standings, adv, has_ratings)


def _roster(season: str, team: str) -> None:
    section("Roster")
    roster = players.team_roster(season, team, min_games=5)
    roster["note"] = [tm.move_note(p, team) for p in roster["team_label"]]
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


def _footnote(a: pd.Series | None) -> None:
    """One footnote for the whole tab instead of a caption under every block."""
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


def render_team(season: str, standings: pd.DataFrame) -> None:
    """The Team tab: a team picker, then its sections top to bottom."""
    pick: str | None = st.selectbox("Team", standings["team_name"], label_visibility="collapsed")
    row = standings[standings.team_name == pick].iloc[0]
    games = team_data.team_game_log(int(row.team_id), season)

    conf_table = standings[standings.conf == row.conf].reset_index(drop=True)
    seed = int(conf_table.index[conf_table.team == row.team][0]) + 1
    st.markdown(f"### {T.team_dot(row.team, 14)}{row.team_name}", unsafe_allow_html=True)

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

    _ratings(season, row, seed, adv, a)
    if len(games):
        _splits(games, standings)
    render_profile(season, int(row.team_id), row.team, adv, a)
    render_breakdown(season, row.team)
    _charts(games, standings, adv, season, row.team, a is not None)
    _roster(season, row.team)
    _footnote(a)
