"""Schedule - the season's games on a month calendar.

Pick a day to see its games: final scores with the top scorer (and a jump
to the game on the Games page), or tip-off times with the model's pick.
With a team chosen, the calendar shows its opponents and the page ends
with its whole season and running record.

The season is the sidebar's. A schedule is published weeks before
opening night and covers only a couple of seasons, so when the sidebar is
on a season it doesn't hold, the page shows the season under way (or the
next to start) and says so in one caption.
"""

from __future__ import annotations

import calendar
import html
from datetime import date, datetime
from typing import Any

import pandas as pd
import streamlit as st

from core.fmt import matchup as opponent_label
from dashboard.lib import glossary, matchup, nav, tables
from dashboard.lib import theme as T
from dashboard.lib.data import core as data_core
from dashboard.lib.data import schedule as sched
from dashboard.lib.data import seasons
from dashboard.lib.state import GAMES_PICK_KEY, SEASON_KEY
from dashboard.lib.tables import Col

# Session-state keys. The team is stored apart from its box's own key, like
# the month and the day, so it outlives a visit to another page (Streamlit
# drops a widget's state when a run doesn't draw it).
TEAM_KEY = "sched_team"
TEAM_BOX_KEY = "sched_team_box"
MONTH_KEY = "sched_month"  # the first of the month shown
DAY_KEY = "sched_selected_day"

ALL_TEAMS = "All teams"
TBD = "TBD"  # a team not yet known
PENDING = "Result pending"  # a game before today that has no result yet
TODAY_MARK = "● "
WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
_CALENDAR = calendar.Calendar(firstweekday=calendar.SUNDAY)
_TABLES = (
    "main_staging.stg_schedule",
    "main_marts.fct_team_game",
    "main_staging.stg_player_game_logs",
)


def today() -> date:
    """Today on the league's clock (US Eastern), which is how the schedule
    dates its games. A function, so tests can fix the date."""
    return datetime.now(matchup.EASTERN).date()


# --- Pure helpers ---------------------------------------------------------------


def default_season(spans: pd.DataFrame, on: date) -> str:
    """The season under way on `on`, or the next one to start; the newest
    when every season has ended. `spans` is schedule_seasons()."""
    # Oldest first.
    for season, last_day in zip(spans["season"][::-1], spans["last_day"][::-1], strict=True):
        if last_day >= on:
            return str(season)
    return str(spans["season"].iloc[0])


def month_start(day: date) -> date:
    return day.replace(day=1)


def shift_month(first: date, months: int) -> date:
    index = first.year * 12 + first.month - 1 + months
    return date(index // 12, index % 12 + 1, 1)


def default_month(first_day: date, last_day: date, on: date) -> date:
    """`on`'s month when it falls inside the season, else the first month."""
    if month_start(first_day) <= month_start(on) <= month_start(last_day):
        return month_start(on)
    return month_start(first_day)


def default_day(month: date, on: date, game_days, team_days=()) -> date:
    """`on` when it is in the month, else the month's first day with games
    (the chosen team's, when it plays that month), else the 1st."""
    if month_start(on) == month:
        return on
    for days in (team_days, game_days):
        in_month = sorted(d for d in days if month_start(d) == month)
        if in_month:
            return in_month[0]
    return month


def seasons_sentence(options: list[str]) -> str:
    """['2025-26', '2026-27'] -> '2025-26 and 2026-27' (oldest first)."""
    ordered = sorted(options)
    if len(ordered) < 2:
        return "".join(ordered)
    return f"{', '.join(ordered[:-1])} and {ordered[-1]}"


def day_label(day: date, detail: str, is_today: bool) -> str:
    """A calendar button's label: the day number, then `detail` ("12 games",
    "vs BOS") in italics, which theme.py's calendar CSS draws after a
    middle dot on a wide screen and as a small second line on a phone."""
    label = f"{day.day} *{detail}*" if detail else f"{day.day}"
    return f"{TODAY_MARK}{label}" if is_today else label


def plain_label(label: str) -> str:
    """day_label as it reads on a wide screen: '23 · 12 games'."""
    return label.replace(" *", " · ").replace("*", "")


def tip_or_pending(tipoff_utc, game_day: date, now: date) -> str:
    """The tip-off time of a game still to come; PENDING for one on an
    earlier day that has no result (postponed, cancelled, or not yet
    refreshed), which a time would wrongly show as upcoming."""
    return PENDING if game_day < now else matchup.tipoff_label(tipoff_utc)


def short_name(name: str) -> str:
    """'Jayson Tatum' -> 'Tatum'; 'Jaren Jackson Jr.' -> 'Jackson Jr.'."""
    parts = name.split(" ", 1)
    return parts[1] if len(parts) == 2 else name


def final_line(r: Any) -> str:
    """'NYK 105 @ BOS 112 · Final · Tatum 34' as HTML, the winning side bold.
    `r` is a finished schedule() row."""
    away_pts, home_pts = int(r.away_points), int(r.home_points)
    away = f"{html.escape(r.away)} {away_pts}"
    home = f"{html.escape(r.home)} {home_pts}"
    if home_pts > away_pts:
        home = f"<b>{home}</b>"
    elif away_pts > home_pts:
        away = f"<b>{away}</b>"
    scorer = ""
    if not tables.is_missing(r.top_scorer):
        scorer = f" · {html.escape(short_name(r.top_scorer))} {int(r.top_points)}"
    return f"{away} @ {home} · Final{scorer}"


def _day_heading(day: date) -> str:
    return f"{day:%A, %B} {day.day}"


def _short_day(day: date) -> str:
    return f"{day:%a, %b} {day.day}"


def _span(spans: pd.DataFrame, season: str) -> tuple[date, date]:
    """(first day, last day) of `season`'s regular season."""
    row = spans[spans["season"] == season]
    return row["first_day"].iloc[0], row["last_day"].iloc[0]


# --- State ----------------------------------------------------------------------


def _season_to_show(spans: pd.DataFrame) -> str:
    """The sidebar's season when the schedule holds it, else the season under
    way or next to start."""
    sidebar = st.session_state.get(SEASON_KEY)
    if sidebar in spans["season"].tolist():
        return str(sidebar)
    return default_season(spans, today())


def _set_month(month: date) -> None:
    st.session_state[MONTH_KEY] = month


def _set_day(day: date) -> None:
    st.session_state[DAY_KEY] = day


def _open_game(game_id: str, season: str) -> None:
    """Runs as the button's callback, before the next script run, while the
    sidebar's season box can still be set."""
    st.session_state[GAMES_PICK_KEY] = game_id
    if season in seasons.seasons():
        st.session_state[SEASON_KEY] = season


# --- Sections -------------------------------------------------------------------


def _month_nav(month: date, first: date, last: date) -> None:
    with st.container(
        key="sched_monthnav", horizontal=True, vertical_alignment="center", wrap=False
    ):
        st.button(
            "◀",
            key="sched_prev",
            disabled=month <= first,
            on_click=_set_month,
            args=(shift_month(month, -1),),
            help="Previous month",
        )
        st.markdown(
            f'<div class="bip-sched-month">{month:%B %Y}</div>',
            unsafe_allow_html=True,
            width="content",
        )
        st.button(
            "▶",
            key="sched_next",
            disabled=month >= last,
            on_click=_set_month,
            args=(shift_month(month, 1),),
            help="Next month",
        )


def _calendar(month: date, details: dict[date, str], selected: date, now: date) -> None:
    """The month grid, Sunday first. Each day is a button; days of the
    neighbouring months are left blank."""
    with st.container(key="sched_cal"):
        # wrap=False: seven columns stay one row on a phone instead of stacking.
        for col, name in zip(st.columns(7, wrap=False), WEEKDAYS, strict=True):
            col.markdown(f'<div class="bip-sched-wd">{name}</div>', unsafe_allow_html=True)
        for week in _CALENDAR.monthdatescalendar(month.year, month.month):
            for col, day in zip(st.columns(7, wrap=False), week, strict=True):
                if day.month != month.month:
                    continue
                col.button(
                    day_label(day, details.get(day, ""), day == now),
                    key=f"sched_day_{day.isoformat()}",
                    type="primary" if day == selected else "secondary",
                    on_click=_set_day,
                    args=(day,),
                    width="stretch",
                    wrap=True,
                )


def _day_view(games: pd.DataFrame, day: date, season: str, now: date) -> None:
    st.markdown(f"#### {_day_heading(day)}")
    if games.empty:
        st.caption("No games.")
        return
    finals = games[games["is_final"].astype(bool)]
    upcoming = games[~games["is_final"].astype(bool)]

    if not finals.empty:
        st.markdown(
            f'<div class="bip-sched-head">Final · top scorer'
            f"{T.tip(glossary.TERMS['Top scorer'])}</div>",
            unsafe_allow_html=True,
        )
        clicked = False
        r: Any
        with st.container(key="sched_finals"):
            for r in finals.itertuples():
                row = st.container(horizontal=True, vertical_alignment="center", wrap=False)
                row.markdown(
                    f'<div class="bip-sched-row">{final_line(r)}</div>',
                    unsafe_allow_html=True,
                    width="stretch",
                )
                clicked |= row.button(
                    "Open game",
                    key=f"sched_open_{r.game_id}",
                    on_click=_open_game,
                    args=(r.game_id, season),
                )
        if clicked:
            nav.go("games")

    if not upcoming.empty:
        rows = pd.DataFrame(
            {
                "tip": [tip_or_pending(t, day, now) for t in upcoming["tipoff_utc"]],
                "game": [
                    matchup.favourite_matchup_html(a, h, p)
                    for a, h, p in zip(
                        upcoming["away"],
                        upcoming["home"],
                        upcoming["win_probability"],
                        strict=True,
                    )
                ],
            }
        )
        cols = [
            Col("tip", "Tip-off", left=True),
            Col(
                "game",
                "Matchup · model pick",
                fmt=str,
                left=True,
                help=glossary.TERMS["Model pick"],
            ),
        ]
        st.markdown(tables.html_table(rows, cols), unsafe_allow_html=True)


def _team_season(season: str, team: str, now: date) -> None:
    games = sched.team_schedule(season, team)
    st.markdown(f"#### {html.escape(team)} schedule")
    if games.empty:
        st.caption("No games.")
        return
    final = games["is_final"].astype(bool)
    rows = pd.DataFrame(
        {
            "day": [_short_day(pd.Timestamp(d).date()) for d in games["game_date"]],
            "opp": [
                opponent_label(not home, opp)
                for home, opp in zip(games["is_home"], games["opponent"], strict=True)
            ],
            "result": [
                res if f else tip_or_pending(t, pd.Timestamp(d).date(), now)
                for res, f, t, d in zip(
                    games["result"], final, games["tipoff_utc"], games["game_date"], strict=True
                )
            ],
            "record": games["record"],
        }
    )

    def result_css(v) -> str:
        return {"W": "pos", "L": "neg"}.get(str(v)[:1], "")

    cols = [
        Col("day", "Date", left=True),
        Col("opp", "Opponent", left=True),
        Col("result", "Result", left=True, help=glossary.TERMS["Result"], css=result_css),
        Col("record", "Record", help=glossary.TERMS["Record"]),
    ]
    st.markdown(tables.html_table(rows, cols, max_height=460), unsafe_allow_html=True)


# --- Page -----------------------------------------------------------------------


def render() -> None:
    if not data_core.objects_exist(*_TABLES):
        st.markdown("## Schedule")
        st.info("This warehouse has no schedule yet; it arrives with the next data refresh.")
        return
    spans = sched.schedule_seasons()
    if spans.empty:
        st.markdown("## Schedule")
        st.info("No schedule has been published yet.")
        return

    season = _season_to_show(spans)
    first_day, last_day = _span(spans, season)
    first, last = month_start(first_day), month_start(last_day)
    games = sched.schedule(season)
    # NBA Cup knockout games are scheduled before their teams are known.
    teams = [ALL_TEAMS, *sorted(set(games["home"].dropna()) | set(games["away"].dropna()))]
    games[["home", "away"]] = games[["home", "away"]].fillna(TBD)
    now = today()

    st.markdown(f"## Schedule &nbsp;{T.chip(season)}", unsafe_allow_html=True)
    sidebar = st.session_state.get(SEASON_KEY)
    if sidebar and sidebar != season:
        st.caption(
            f"The schedule covers {seasons_sentence(spans['season'].tolist())}; showing {season}."
        )

    # The widget's own state is dropped on a run that doesn't draw it, so the
    # team is kept in TEAM_KEY and put back before the box is drawn; while
    # the page is up, the box is the truth.
    remembered = st.session_state.get(TEAM_KEY)
    st.session_state.setdefault(TEAM_BOX_KEY, remembered if remembered in teams else ALL_TEAMS)
    # A team the season doesn't have (the sidebar moved to another season).
    if st.session_state[TEAM_BOX_KEY] not in teams:
        st.session_state[TEAM_BOX_KEY] = ALL_TEAMS
    team = st.selectbox("Team", teams, key=TEAM_BOX_KEY, label_visibility="collapsed")
    st.session_state[TEAM_KEY] = team

    month = st.session_state.get(MONTH_KEY)
    if not isinstance(month, date) or not first <= month <= last:
        month = default_month(first_day, last_day, now)
    st.session_state[MONTH_KEY] = month

    mine = games if team == ALL_TEAMS else games[(games["home"] == team) | (games["away"] == team)]
    game_days = {pd.Timestamp(d).date() for d in games["game_date"]}
    team_days = {pd.Timestamp(d).date() for d in mine["game_date"]}
    selected = st.session_state.get(DAY_KEY)
    if not isinstance(selected, date) or month_start(selected) != month:
        selected = default_day(month, now, game_days, team_days)
    st.session_state[DAY_KEY] = selected

    if team == ALL_TEAMS:
        counts = sched.month_counts(season, month.year, month.month)
        details = {d: f"{n} game{'s' if n != 1 else ''}" for d, n in counts.items()}
    else:
        schedule_of_team = sched.team_schedule(season, team)
        details = {
            pd.Timestamp(d).date(): opponent_label(not home, opp)
            for d, home, opp in zip(
                schedule_of_team["game_date"],
                schedule_of_team["is_home"],
                schedule_of_team["opponent"],
                strict=True,
            )
        }

    _month_nav(month, first, last)
    _calendar(month, details, selected, now)

    day_games = mine[mine["game_date"].dt.date == selected]
    # The day's games and the team's season read as lists: kept to a
    # readable width rather than stretched across a wide screen.
    with st.container(key="sched_dayview"):
        _day_view(day_games, selected, season, now)
        if team != ALL_TEAMS:
            _team_season(season, team, now)
