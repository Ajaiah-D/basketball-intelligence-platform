"""The Team tab's league-ranks section: where the team ranks in the league
on each profile stat, from mart_team_profile. It shows the evidence and
leaves the verdict to the reader, so there is no "best at / worst at" line.

A warehouse published before that mart gets the old Four Factors table
instead, with one notice line, until a refresh brings the mart.
"""

import pandas as pd
import streamlit as st

from dashboard.lib import diagnosis, glossary, viz, viz_diagnosis
from dashboard.lib import team_metrics as tm
from dashboard.lib.data import diagnosis as diagnosis_data
from dashboard.views.teams.common import ROW_HEIGHT, section


def render_profile(
    season: str, team_id: int, team: str, adv: pd.DataFrame, a: pd.Series | None
) -> None:
    """The section for one team-season. `adv` and `a` (the team's
    mart_team_season row, None without ratings) feed only the fallback."""
    if not diagnosis_data.profile_available():
        st.info("League ranks for every key stat arrive with the next data refresh.")
        if a is not None and "effective_fg_pct" in adv and a.effective_fg_pct == a.effective_fg_pct:
            four_factors(adv, team)
        return

    league = diagnosis_data.team_profile(season)
    match = league[league["team_id"] == team_id]
    if match.empty:
        return
    row = {str(k): v for k, v in match.iloc[0].items()}
    # Early seasons have no inputs for any rank: like the Four Factors before
    # it, the section simply doesn't show.
    if not any(pd.notna(row.get(f"{stat.key}_pctile")) for stat in diagnosis.PROFILE_STATS):
        return

    section("How they rank in the league", glossary.TERMS["League ranks"])
    fig = viz_diagnosis.profile_chart(row, league_size=len(league))
    st.plotly_chart(fig, config=viz.PLOTLY_CONFIG, width="stretch")


def four_factors(adv: pd.DataFrame, team: str) -> None:
    """The pre-profile table: each factor on offense and defense against the
    league average, with ranks."""
    section("Four Factors", glossary.TERMS["Four Factors"])
    ff = tm.four_factors(adv, team)
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
