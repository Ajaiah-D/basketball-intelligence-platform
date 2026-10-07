"""Finances - what teams spend, against the league's salary cap, luxury tax
and apron lines.

Reads top to bottom as three questions: how did the league spend that
season, what do the lines mean, and where does one team sit and why (its
biggest contracts) - with the franchise's whole history below. Every number
has a sentence next to it (dashboard/lib/payroll.py): the first version of
this page showed bare figures and "Over cap" on nearly every team, with no
word that a soft cap makes that normal.
"""

import html

import pandas as pd
import streamlit as st

from dashboard.lib import db, franchises, payroll
from dashboard.lib import theme as T
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


def _contracts_card(contracts: pd.DataFrame) -> str:
    rows = [
        f'<div class="bip-row">{T.rank_badge(int(r.salary_rank))}'
        f'<span class="bip-name">{html.escape(str(r.player))}</span>'
        f'<span class="bip-team">{r.share_of_payroll:.0%}</span>'
        f'<span class="bip-val">{payroll.money(r.salary_usd)}</span></div>'
        for r in contracts.head(5).itertuples()
    ]
    return f'<div class="bip-card"><h4>Biggest contracts</h4>{"".join(rows)}</div>'


def _render_team_season(team_df: pd.DataFrame, league: pd.DataFrame,
                        team_name: str, season: str) -> None:
    row_df = team_df[team_df["season"] == season]
    if row_df.empty:
        st.info(f"No payroll data for the {team_name} in {season}.")
        return
    row = row_df.iloc[0]
    contracts = (db.team_contracts(season, row["team_abbreviation"])
                 if db.team_contracts_available() else None)
    rank = payroll.league_rank(league, row["team_abbreviation"])
    st.markdown(payroll.team_summary(row, row["era_name"], rank, contracts))

    label, color = payroll.bracket(row)
    reliable = label != "Data incomplete"
    k1, k2, k3 = st.columns(3)
    k1.markdown(T.kpi("Payroll", payroll.money(row["team_payroll"]) if reliable else "N/A"),
                unsafe_allow_html=True)
    k2.markdown(T.kpi("League rank",
                      f"{payroll.ordinal(rank[0])} of {rank[1]}" if rank else "N/A"),
                unsafe_allow_html=True)
    k3.markdown(T.kpi("Status", label, accent=color), unsafe_allow_html=True)
    if contracts is not None and len(contracts) and reliable:
        st.markdown(_contracts_card(contracts), unsafe_allow_html=True)


def render() -> None:
    st.markdown("## Finances", unsafe_allow_html=True)

    if not db.team_finances_available():
        st.info("Payroll data hasn't been loaded into this warehouse yet.")
        return

    all_seasons = db.team_payroll_history()
    if all_seasons.empty:
        st.info("No payroll data available.")
        return
    all_seasons = franchises.annotate(all_seasons)
    cap_df = db.salary_cap_history()

    fetched = (all_seasons["payroll_fetched_at_utc"].max()
               if "payroll_fetched_at_utc" in all_seasons else None)
    st.caption(payroll.freshness_text(fetched, all_seasons["season"].max(),
                                      cap_df["season"].max()))

    seasons = sorted(all_seasons["season"].unique(), reverse=True)
    teams = sorted(all_seasons["franchise"].unique(), key=franchises.franchise_name)
    f1, f2 = st.columns(2)
    season = f1.selectbox("Season", seasons, index=0)
    team = f2.selectbox("Team", teams, index=teams.index("BOS") if "BOS" in teams else 0,
                        format_func=franchises.franchise_name)
    team_name = franchises.franchise_name(team)
    team_df = all_seasons[all_seasons["franchise"] == team].sort_values("season")
    league = all_seasons[all_seasons["season"] == season]

    # --- The league that season ---------------------------------------------
    st.markdown(f"### The league in {season}")
    st.markdown(payroll.league_summary(league, season))
    snapshot = payroll.reliable(league).copy()
    snapshot["team_name"] = snapshot["era_name"]
    snapshot["bar_color"] = [payroll.bracket(r)[1] for _, r in snapshot.iterrows()]
    this_season = team_df[team_df["season"] == season]
    highlight = this_season["era_name"].iloc[0] if len(this_season) else None
    st.plotly_chart(viz.league_payroll_snapshot(snapshot, highlight=highlight),
                    width="stretch", config=viz.PLOTLY_CONFIG)

    with st.expander("How to read this", expanded=True):
        st.markdown(payroll.HOW_TO_READ)

    # --- The team -------------------------------------------------------------
    st.markdown(f"### {team_name}")
    note = franchises.FRANCHISE_NOTES.get(team)
    if note:
        st.caption(note)
    _render_team_season(team_df, league, team_name, season)

    st.markdown("#### Payroll history")
    if (team_df["season"] < EARLY_ERA_CUTOFF).any():
        st.caption(
            "Seasons before 1996-97 use payroll figures Basketball-Reference "
            "itself notes are partly reconstructed for players with missing "
            "records - treat early-era numbers as directionally right, not exact."
        )
    st.plotly_chart(viz.team_finances_trend(team_df, cap_df,
                                            eras=franchises.era_spans(team_df)),
                    width="stretch", config=viz.PLOTLY_CONFIG)
    _render_incomplete_caption(team_df)

    display_df = team_df[["season", "era_name", "team_payroll", "salary_cap", "luxury_tax",
                          "first_apron", "second_apron", "payroll_pct_of_cap"]].copy()
    # Stored as a ratio (1.23 = 123% of cap); NumberColumn's printf format
    # doesn't scale for us.
    display_df["payroll_pct_of_cap"] = display_df["payroll_pct_of_cap"] * 100
    display_df["status"] = [payroll.bracket(r)[0] for _, r in team_df.iterrows()]
    display_df = display_df.rename(columns={
        "season": "Season", "era_name": "Team", "team_payroll": "Payroll",
        "salary_cap": "Salary cap", "luxury_tax": "Luxury tax",
        "first_apron": "1st apron", "second_apron": "2nd apron",
        "payroll_pct_of_cap": "% of cap", "status": "Status",
    })
    money_col = st.column_config.NumberColumn(format="$%,.0f")
    with st.expander("Show full season-by-season table"):
        st.dataframe(
            display_df, hide_index=True, width="stretch",
            column_config={
                "Payroll": money_col, "Salary cap": money_col, "Luxury tax": money_col,
                "1st apron": money_col, "2nd apron": money_col,
                "% of cap": st.column_config.NumberColumn(format="%.0f%%"),
            },
        )

    st.caption(payroll.METHOD_NOTE)
