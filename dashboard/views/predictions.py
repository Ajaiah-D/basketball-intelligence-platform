"""Upcoming game predictions and the model's public track record.

The next week's games are a compact list, one table a day, each row the
matchup with the model's favourite marked (lib/matchup.py, the format the
Schedule page uses too), its chance and the margin it expects. Below it,
the track record: three numbers, the details behind them, and the latest
settled games.
"""

from __future__ import annotations

import html
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd
import streamlit as st

from dashboard.lib import glossary, matchup, nav, stats, viz
from dashboard.lib import theme as T
from dashboard.lib.data import predictions
from dashboard.lib.tables import Col, html_table

DAYS_AHEAD = 7  # the upcoming list: today and the six days after it
RECENT_GAMES = 10  # settled games listed under the track record
DETAILS = "How the model works and how well-calibrated it is"


def today() -> date:
    """Today in US Eastern time, the clock the schedule's dates are on.
    Tests replace it, so they don't depend on the day they run."""
    return datetime.now(matchup.EASTERN).date()


def _day(d) -> str:
    """'Tue, Oct 20' - no zero-padded day, and no platform-specific strftime."""
    return f"{d:%a, %b} {d.day}"


def _upcoming(upcoming: pd.DataFrame) -> pd.DataFrame:
    """Adds the tip-off label, and the Eastern date games are grouped by
    (falls back to the schedule date when the tip-off isn't known)."""
    df = upcoming.copy()
    # Plain lists, not a Timestamp column: pandas turns a None in a column of
    # tz-aware Timestamps into NaT, and NaT.date() is NaT, which groupby drops.
    tips = [matchup.eastern_tipoff(t) for t in df["tipoff_utc"]]
    df["tip_label"] = [matchup.tipoff_label(t) for t in df["tipoff_utc"]]
    df["day_et"] = [
        t.date() if t is not None else pd.Timestamp(g).date()
        for t, g in zip(tips, df["game_date"], strict=True)
    ]
    # Within a day: by tip-off, unknown times last.
    df["sort_key"] = [t.value if t is not None else float("inf") for t in tips]
    return df.sort_values(["day_et", "sort_key", "game_id"], kind="stable")


def _day_table(day: date, games: pd.DataFrame) -> str:
    """One day's games as a four-column table, the date heading its
    tip-off column."""
    trios = list(
        zip(
            games["away_team_abbreviation"],
            games["home_team_abbreviation"],
            games["win_probability"],
            strict=True,
        )
    )
    rows = pd.DataFrame(
        {
            "tip": games["tip_label"].tolist(),
            "game": [matchup.matchup_html(a, h, p) for a, h, p in trios],
            "chance": [matchup.chance_html(a, h, p) for a, h, p in trios],
            "margin": [matchup.margin_label(m) for m in games["predicted_margin"]],
        }
    )
    cols = [
        Col("tip", _day(day), left=True),
        Col("game", "Matchup", fmt=str, left=True, help=glossary.TERMS["Model pick"]),
        Col("chance", "Chance", fmt=str, left=True, help=glossary.TERMS["Chance"]),
        Col("margin", "Margin", help=glossary.TERMS["Predicted margin"]),
    ]
    return f'<div class="bip-upcoming">{html_table(rows, cols)}</div>'


def _upcoming_section(upcoming: pd.DataFrame) -> None:
    if upcoming.empty:
        st.info(f"No games in the next {DAYS_AHEAD} days.")
    else:
        day: Any  # a date; pandas-stubs type groupby keys as any scalar
        for day, group in _upcoming(upcoming).groupby("day_et", sort=True):
            st.markdown(_day_table(day, group), unsafe_allow_html=True)
    if st.button(
        "Later games are on the Schedule page",
        key="pred_to_schedule",
        type="tertiary",
        icon=":material/calendar_month:",
    ):
        nav.go("schedule")


def _track_record(upcoming: pd.DataFrame) -> bool:
    """The KPI row, or one line saying why there is none. Whether any game
    has settled."""
    st.markdown("#### Track record")
    if not predictions.settled_available():
        # A warehouse published before mart_settled_predictions existed.
        st.info("The track record appears after the next data refresh.")
        return False
    record = predictions.prediction_track_record()
    if record["n"] == 0:
        if upcoming.empty:
            st.info(
                "No predictions have been settled yet. Check back after the first games are played."
            )
        else:
            first = _upcoming(upcoming).iloc[0]["day_et"]
            st.info(f"The first predictions settle after opening night ({_day(first)}).")
        return False

    tiles = [
        ("Accuracy", f"{record['accuracy'] * 100:.1f}%"),
        ("Brier score", f"{record['brier']:.3f}"),
        ("Margin error", f"{record['margin_mae']:.1f}"),
    ]
    for col, (label, value) in zip(st.columns(3), tiles, strict=True):
        col.markdown(T.kpi(label, value, help=glossary.TERMS[label]), unsafe_allow_html=True)
    st.caption(f"Settled games: {record['n']:,}")
    return True


def _details(settled: bool) -> None:
    with st.expander(DETAILS):
        st.markdown(
            "Every team carries an Elo rating, a running score that rises with wins "
            "and falls with losses, adjusted for how strong the opponent was. A "
            "ridge regression turns the gap between the two teams' ratings, plus "
            "home court, into an expected "
            f"point margin{T.tip(glossary.TERMS['Predicted margin'])}, and a second "
            "step converts that margin into a "
            f"win probability{T.tip(glossary.TERMS['Win probability'])}. Recent form "
            "and rest days are not yet worked out for future games, so for now these "
            "picks lean on ratings alone.",
            unsafe_allow_html=True,
        )
        # calibration_bins is empty below its 50-game minimum: a chart of a
        # handful of games would only show noise.
        bins = stats.calibration_bins(predictions.settled_predictions()) if settled else None
        if bins is not None and not bins.empty:
            st.markdown(
                f"**Calibration**{T.tip(glossary.TERMS['Calibration'])}", unsafe_allow_html=True
            )
            st.caption("When the model gave the home team a chance, how often it won.")
            st.plotly_chart(viz.calibration_chart(bins), config=viz.PLOTLY_CONFIG, width="stretch")


def _recent_table(recent: pd.DataFrame) -> str:
    rows = []
    # pandas-stubs type each itertuples field as any scalar; the columns are
    # only known at runtime.
    r: Any
    for r in recent.itertuples():
        # A coin flip is a home pick, the rule the accuracy KPI grades with.
        home_pick, pct = matchup.favourite_pct(r.win_probability)
        pick = r.home if home_pick else r.away
        winner = r.home if r.home_pts > r.away_pts else r.away
        hi, lo = max(r.home_pts, r.away_pts), min(r.home_pts, r.away_pts)
        rows.append(
            {
                "game": f"{r.away} @ {r.home}",
                "pick": f'<b style="color:{T.team_color(pick)}">{html.escape(pick)}</b>',
                "chance": f"{pct}%",
                "final": f"{winner} {hi}-{lo}",
                "correct": "✓" if r.correct else "✗",
            }
        )
    cols = [
        Col("game", "Matchup", left=True),
        Col("pick", "Pick", fmt=str, left=True, help=glossary.TERMS["Pick"]),
        Col("chance", "Chance", help=glossary.TERMS["Chance"]),
        Col("final", "Final", left=True, help=glossary.TERMS["Final"]),
        Col(
            "correct",
            "Correct",
            help=glossary.TERMS["Correct"],
            css=lambda v: "pos" if v == "✓" else "neg",
        ),
    ]
    return f'<div class="bip-recent">{html_table(pd.DataFrame(rows), cols)}</div>'


def render() -> None:
    st.markdown("## Predictions", unsafe_allow_html=True)

    if not predictions.predictions_available():
        st.info(
            "No predictions have been published yet. They are written once a "
            "week, before the games are played."
        )
        return

    st.caption(
        f"The model's pick for each game in the next {DAYS_AHEAD} days, and how "
        "its settled picks have done."
    )
    now = today()
    upcoming = predictions.upcoming_predictions(now, now + timedelta(days=DAYS_AHEAD - 1))
    _upcoming_section(upcoming)

    settled = _track_record(upcoming)
    _details(settled)
    if settled:
        recent = predictions.recent_settled_predictions(RECENT_GAMES)
        st.markdown("#### Recent results")
        st.markdown(_recent_table(recent), unsafe_allow_html=True)
