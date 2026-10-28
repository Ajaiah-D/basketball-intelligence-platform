"""The Team tab's player breakdown: for one area of the team's game (an
entry of diagnosis.AREAS), the team's league rank in it and each rotation
player's measures against the league median, with a way to open any of
them on the Players page.

It shows the evidence and leaves the reading to the viewer: no sentence
here says who is good or bad at anything. The captions only explain the
method and its limits.

A warehouse published before the diagnosis marts gets nothing here; the
league-ranks section above already shows the one notice line for both.
"""

from __future__ import annotations

import html
from typing import Any

import pandas as pd
import streamlit as st

from dashboard.lib import diagnosis, glossary, nav, tables, viz, viz_diagnosis
from dashboard.lib import theme as T
from dashboard.lib.data import diagnosis as diagnosis_data
from dashboard.lib.state import PLAYERS_PICK_KEY, SEASON_KEY
from dashboard.views.teams.common import section

AREA_KEY = "teams_breakdown_area"
OPEN_KEY = "teams_breakdown_player"
# Up to this many rotation players get a button each; more get a picker
# and one button, which stays one row on a phone.
MAX_BUTTONS = 8

# Columns the table adds for an area beyond its measures: the share of the
# team's threes behind 3PA per game, and the two ratings behind on/off.
_EXTRA = {
    "three_point": [
        diagnosis.Measure("team_three_pa_share", "Share of team 3PA", "3PA share", "share"),
    ],
    "on_off": [
        diagnosis.Measure("on_court_def_rating", "DRtg on", "Def. on/off", "num"),
        diagnosis.Measure("est_off_court_def_rating", "DRtg off (est.)", "Def. on/off", "num"),
    ],
}


def _in_sentence(label: str) -> str:
    """'Turnover rate' -> 'turnover rate' after "in"; 'eFG%' and 'FT rate'
    keep their case."""
    if len(label) > 1 and label[0].isupper() and not label[1].isupper():
        return label[0].lower() + label[1:]
    return label


def _rank_chip(season: str, team: str, area: diagnosis.Area) -> str:
    """'Team: #4 of 30 in 3P%' with the team stat's glossary tip, or "" when
    the team has no rank in it that season."""
    league = diagnosis_data.team_profile(season)
    match = league[league["team_abbreviation"] == team]
    if match.empty or diagnosis.missing(match.iloc[0].get(area.team_rank_col)):
        return ""
    rank = int(match.iloc[0][area.team_rank_col])
    stat = diagnosis.PROFILE_BY_KEY[area.team_stat]
    text = f"Team: #{rank} of {len(league)} in {_in_sentence(stat.label)}"
    return f"{T.chip(html.escape(text))}{T.tip(glossary.TERMS[stat.term])}"


def _value_cell(m: diagnosis.Measure):
    return lambda v: html.escape(m.format(v))


def _minutes_cell(v: Any) -> str:
    return "-" if diagnosis.missing(v) else f"{round(float(v)):,}"


def _table(rows: pd.DataFrame, area: diagnosis.Area) -> str:
    """The numbers behind the chart: one row per player and a league-median
    footer under the measures."""
    measures = [*area.measures, *_EXTRA.get(area.key, [])]
    cols = [
        tables.Col("player", "Player", left=True, css=lambda _: "name"),
        tables.Col("games_played", "GP", help=glossary.TERMS["GP"]),
        tables.Col("minutes", "Min", fmt=_minutes_cell, help="Minutes played for this team."),
    ]
    cols += [
        tables.Col(m.col, m.label, fmt=_value_cell(m), help=glossary.TERMS[m.term])
        for m in measures
    ]
    foot = {"player": "League median"}
    for m in area.measures:
        median = rows.get(f"{m.col}_league_median")
        if median is not None and len(median.dropna()):
            foot[m.col] = html.escape(m.format(median.dropna().iloc[0]))
    shown = rows.reindex(columns=[c.key for c in cols])
    return tables.html_table(shown, cols, foot=foot)


def _preset_player(player: str, season: str) -> None:
    """Button callback: tell the Players page whom to open. It runs before
    the next script run, while the sidebar's season box can still be set."""
    st.session_state[PLAYERS_PICK_KEY] = player
    st.session_state[SEASON_KEY] = season


def _open_on_players(rows: pd.DataFrame, season: str) -> None:
    players = rows["player"].tolist()
    st.markdown("**Open a player on the Players page**")
    clicked = False
    if len(players) <= MAX_BUTTONS:
        cols = st.columns(len(players))
        for i, (col, player) in enumerate(zip(cols, players, strict=True)):
            clicked |= col.button(
                player,
                key=f"{OPEN_KEY}_{i}",
                on_click=_preset_player,
                args=(player, season),
                width="stretch",
            )
    else:
        pick_col, go_col = st.columns([3, 1])
        player = pick_col.selectbox("Player", players, key=OPEN_KEY, label_visibility="collapsed")
        clicked = go_col.button(
            "Open on Players →",
            key=f"{OPEN_KEY}_go",
            on_click=_preset_player,
            args=(player, season),
            width="stretch",
        )
    if clicked:
        nav.go("players")


def _no_data_note(rows: pd.DataFrame, area: diagnosis.Area, team: str, season: str) -> str:
    """The line shown instead of the chart when no player has any of the
    area's measures, or "" when someone does."""
    have = [m.col for m in area.measures if m.col in rows.columns]
    if any(rows[c].notna().any() for c in have):
        return ""
    if area.key == "on_off":
        return (
            f"No {team} player has an on/off estimate in {season}: it needs 500+ "
            "minutes with one team, from 1996-97."
        )
    return f"No player numbers for {area.label.lower()} in {season}."


def render_breakdown(season: str, team: str) -> None:
    """The section for one team-season: an area picker, the team's rank in
    it, the rotation chart, the area's caption, the numbers and the
    Players links."""
    if not diagnosis_data.profile_available():
        return
    cut = diagnosis_data.rotation_min_games(season)
    rows = diagnosis_data.team_drivers(season, team)

    section("Player breakdown", glossary.TERMS["Player breakdown"])
    if rows.empty:
        st.caption(f"No {team} player has {cut}+ games for the team in {season}.")
        return
    if cut < diagnosis_data.ROTATION_MIN_GAMES:
        st.caption(f"Early in the season: players with {cut}+ games for the team.")
    by_label = {a.label: a for a in diagnosis.AREAS}
    pick_col, chip_col = st.columns([2, 3], vertical_alignment="center")
    label = pick_col.selectbox("Area", list(by_label), key=AREA_KEY, label_visibility="collapsed")
    area = by_label[label or diagnosis.AREAS[0].label]
    chip = _rank_chip(season, team, area)
    if chip:
        chip_col.markdown(chip, unsafe_allow_html=True)

    note = _no_data_note(rows, area, team, season)
    if note:
        st.caption(note)
    else:
        fig = viz_diagnosis.drivers_chart(rows, area, team)
        st.plotly_chart(fig, config=viz.PLOTLY_CONFIG, width="stretch")
        st.caption(area.caption)
        with st.expander("The numbers"):
            # In a card: the table's sticky name column has the card's surface.
            st.markdown(f'<div class="bip-card">{_table(rows, area)}</div>', unsafe_allow_html=True)
    _open_on_players(rows, season)
