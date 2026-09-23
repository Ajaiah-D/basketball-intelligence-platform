"""Team payroll history vs. the league salary cap, luxury tax, and apron lines."""

import pandas as pd
import streamlit as st

from dashboard.lib import db
from dashboard.lib import viz

EARLY_ERA_CUTOFF = "1996-97"  # Basketball-Reference's own salary data before this era is
                               # acknowledged by them to be partly extrapolated/minimum-filled


# mart_team_finances.payroll_incomplete_reason values that really do mean
# "Basketball-Reference is missing rows", as opposed to "the number is real
# but low". Saying the wrong one of those about a specific team-season is a
# published factual claim about that team's history, so the two get
# different sentences - see the column's docs in _marts_models.yml.
_SOURCE_GAP_REASONS = ("no_source_data", "sparse_source_data")


def _render_incomplete_caption(team_df) -> None:
    """Explain this team's payroll_likely_incomplete seasons, per reason.

    The single sentence this used to print claimed the source was missing
    most of the roster for every flagged season. That is true for the
    source-gap reasons and false for 'below_half_cap', whose only occurrence
    in the whole mart is 1988-89 Miami - 13 real players, 47% of that year's
    cap, an inaugural expansion roster that was genuinely that cheap. The
    page was publishing a wrong claim about a real NBA season.
    """
    flagged = team_df[team_df["payroll_likely_incomplete"]]
    if flagged.empty:
        return

    # A warehouse published before payroll_incomplete_reason existed (the
    # deployed app reads whatever the last release published) has the flag
    # but not the reason. Rather than guess - guessing is what the bug was -
    # those rows get the third sentence below, which claims only what the
    # flag itself claims.
    if "payroll_incomplete_reason" in flagged:
        reason = flagged["payroll_incomplete_reason"]
    else:
        reason = pd.Series(None, index=flagged.index, dtype=object)

    source_gap = flagged.loc[reason.isin(_SOURCE_GAP_REASONS), "season"].tolist()
    low_only = flagged.loc[reason == "below_half_cap", "season"].tolist()
    unattributed = flagged.loc[
        ~reason.isin((*_SOURCE_GAP_REASONS, "below_half_cap")), "season"].tolist()

    if source_gap:
        st.caption(
            f"No reliable payroll total exists for {', '.join(source_gap)} - "
            "Basketball-Reference's own salary records for that season are missing "
            "most of the roster, not just this team. Shown as a gap in the chart "
            "below rather than a low number."
        )
    if low_only:
        st.caption(
            f"Payroll data for {', '.join(low_only)} is unusually low relative to "
            "that season's cap and may not reflect the full picture, so it is shown "
            "as a gap in the chart below rather than a low number."
        )
    if unattributed:
        st.caption(
            f"Payroll data for {', '.join(unattributed)} may not reflect the full "
            "picture, so it is shown as a gap in the chart below rather than a "
            "low number."
        )


def render() -> None:
    st.markdown("## Finances", unsafe_allow_html=True)

    if not db.team_finances_available():
        st.info("Payroll data hasn't been loaded into this warehouse yet.")
        return

    all_seasons = db.team_payroll_history()
    if all_seasons.empty:
        st.info("No payroll data available.")
        return

    # One entry per franchise, not per abbreviation: GOS/GSW, PHL/PHI,
    # SAN/SAS and UTH/UTA are each one team under nba_api's 1996-97 code
    # rename, and listing both halves separately hands the user a 12-season
    # chart and a 30-season chart instead of the 42-season history this page
    # exists to show. See db.MERGED_FRANCHISES.
    teams = db.franchise_options(all_seasons["team_abbreviation"])
    default_ix = teams.index("BOS") if "BOS" in teams else 0
    team = st.selectbox("Team", teams, index=default_ix, label_visibility="visible")

    codes = db.franchise_codes(team)
    team_df = all_seasons[all_seasons["team_abbreviation"].isin(codes)]
    cap_df = db.salary_cap_history()

    if len(codes) > 1:
        legacy = ", ".join(c for c in codes if c != team)
        st.caption(
            f"{team} includes this franchise's pre-1996-97 seasons, which the "
            f"source data files under {legacy} - same team, renamed code."
        )

    if (team_df["season"] < EARLY_ERA_CUTOFF).any():
        st.caption(
            "Seasons before 1996-97 use payroll figures Basketball-Reference "
            "itself notes are partly reconstructed for players with missing "
            "records - treat early-era numbers as directionally right, not exact."
        )

    _render_incomplete_caption(team_df)

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
