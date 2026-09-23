"""Team payroll history vs. the league salary cap, luxury tax, and apron lines."""

import streamlit as st

from dashboard.lib import db
from dashboard.lib import viz

EARLY_ERA_CUTOFF = "1996-97"  # Basketball-Reference's own salary data before this era is
                                # acknowledged by them to be partly extrapolated/minimum-filled


def render() -> None:
    st.markdown("## Finances", unsafe_allow_html=True)

    if not db.team_finances_available():
        st.info("Payroll data hasn't been loaded into this warehouse yet.")
        return

    all_seasons = db.team_payroll_history()
    if all_seasons.empty:
        st.info("No payroll data available.")
        return

    teams = sorted(all_seasons["team_abbreviation"].unique())
    default_ix = teams.index("BOS") if "BOS" in teams else 0
    team = st.selectbox("Team", teams, index=default_ix, label_visibility="visible")

    team_df = all_seasons[all_seasons["team_abbreviation"] == team]
    cap_df = db.salary_cap_history()

    if (team_df["season"] < EARLY_ERA_CUTOFF).any():
        st.caption(
            "Seasons before 1996-97 use payroll figures Basketball-Reference "
            "itself notes are partly reconstructed for players with missing "
            "records - treat early-era numbers as directionally right, not exact."
        )

    incomplete_seasons = team_df.loc[team_df["payroll_likely_incomplete"], "season"].tolist()
    if incomplete_seasons:
        st.caption(
            f"No reliable payroll total exists for {', '.join(incomplete_seasons)} - "
            "Basketball-Reference's own salary records for that season are missing "
            "most of the roster, not just this team. Shown as a gap in the chart "
            "below rather than a low number."
        )

    st.plotly_chart(viz.team_finances_trend(team_df, cap_df), width="stretch",
                    config=viz.PLOTLY_CONFIG)

    st.dataframe(
        team_df[["season", "team_payroll", "salary_cap", "luxury_tax",
                "first_apron", "second_apron", "payroll_pct_of_cap",
                "payroll_likely_incomplete", "over_cap", "over_tax",
                "over_first_apron", "over_second_apron"]],
        hide_index=True, width="stretch",
    )

    st.caption("Payroll data via Basketball-Reference.com. League cap/tax/apron "
              "figures are official NBA announcements.")
