"""Upcoming game predictions and the model's public track record."""

from __future__ import annotations

from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from core.constants import HOME_PICK_THRESHOLD
from dashboard.lib import glossary, stats, viz
from dashboard.lib import theme as T
from dashboard.lib.data import predictions

EASTERN = ZoneInfo("America/New_York")


def _day(d) -> str:
    """'Tue, Oct 20' - no zero-padded day, and no platform-specific strftime."""
    return f"{d:%a, %b} {d.day}"


def _eastern_tipoff(tipoff_utc):
    """The tip-off as a US Eastern Timestamp, or None when it isn't known."""
    if tipoff_utc is None or pd.isna(tipoff_utc):
        return None
    return pd.Timestamp(tipoff_utc).tz_localize("UTC").tz_convert(EASTERN)


def _clock(t) -> str:
    if t is None:
        return "TBD"
    return f"{t.hour % 12 or 12}:{t.minute:02d} {'AM' if t.hour < 12 else 'PM'} ET"


def _split(win_probability: float) -> tuple[int, int]:
    """Whole-number (home %, away %) that always add to 100."""
    home = round(float(win_probability) * 100)
    return home, 100 - home


def prediction_card(r, tip: str) -> str:
    """One upcoming game: tip-off time, both teams, a two-color probability
    bar and a plain-English verdict. `r` is a row of an upcoming_predictions
    frame; `tip` is the already-formatted tip-off label."""
    home, away = r.home_team_abbreviation, r.away_team_abbreviation
    home_pct, away_pct = _split(r.win_probability)
    # Trust the probability over the margin's sign if they ever disagree.
    home_fav = float(r.win_probability) >= HOME_PICK_THRESHOLD
    fav, fav_pct = (home, home_pct) if home_fav else (away, away_pct)
    # Never "by 0": a pick that is a coin flip is still a pick by a point.
    by = max(1, round(abs(float(r.predicted_margin))))
    # The underdog's side is dimmed so the favorite reads at a glance; the
    # small gap keeps the split visible when both teams share a color.
    away_op, home_op = (0.5, 1) if home_fav else (1, 0.5)
    bar = (
        f'<div style="display:flex;gap:2px;flex:1;height:8px;margin:0 .55rem;'
        f'border-radius:4px;overflow:hidden">'
        f'<div style="width:{away_pct}%;background:{T.team_color(away)};'
        f'opacity:{away_op}"></div>'
        f'<div style="width:{home_pct}%;background:{T.team_color(home)};'
        f'opacity:{home_op}"></div></div>'
    )
    return (
        f'<div class="bip-game">'
        f'<div class="bip-game-date">{tip}</div>'
        f'<div class="bip-game-line"><span class="tm">{T.team_dot(away)}{away}</span></div>'
        f'<div class="bip-game-line"><span class="tm">{T.team_dot(home)}{home}</span></div>'
        f'<div class="bip-game-line" style="margin-top:.35rem">'
        f'<span class="tm">{away} {away_pct}%</span>{bar}'
        f'<span class="tm">{home} {home_pct}%</span></div>'
        f'<div class="bip-game-line" style="margin-top:.2rem">'
        f'<span class="tm winner">{fav} by {by} · {fav_pct}%</span></div>'
        f"</div>"
    )


def _upcoming(upcoming: pd.DataFrame) -> pd.DataFrame:
    """Adds the Eastern tip-off, and the Eastern date games are grouped by
    (falls back to the schedule date when the tip-off isn't known)."""
    df = upcoming.copy()
    # Plain lists, not a Timestamp column: pandas turns a None in a column of
    # tz-aware Timestamps into NaT, and NaT.date() is NaT, which groupby drops.
    tips = [_eastern_tipoff(t) for t in df["tipoff_utc"]]
    df["tip_label"] = [_clock(t) for t in tips]
    df["day_et"] = [
        t.date() if t is not None else pd.Timestamp(g).date()
        for t, g in zip(tips, df["game_date"], strict=True)
    ]
    # Within a day: by tip-off, unknown times last.
    df["sort_key"] = [t.value if t is not None else float("inf") for t in tips]
    return df.sort_values(["day_et", "sort_key", "game_id"], kind="stable")


def _how_it_works() -> None:
    with st.expander("How these predictions are made"):
        st.markdown(
            "Every team carries an Elo rating, a running score that rises with wins "
            "and falls with losses, adjusted for how strong the opponent was. A "
            "ridge regression turns the gap between the two teams' ratings, plus "
            "home court, into an expected "
            f"point margin{T.tip(glossary.TERMS['Predicted margin'])}, and a second "
            "step converts that margin into a "
            f"win probability{T.tip(glossary.TERMS['Win probability'])}. Recent form "
            "and rest days are not yet worked out for future games, so for now these "
            "picks lean on ratings alone: a solid first pass, not the model's full "
            "strength.",
            unsafe_allow_html=True,
        )


def _upcoming_section(upcoming: pd.DataFrame) -> None:
    df = _upcoming(upcoming)
    for day, group in df.groupby("day_et", sort=True):
        st.markdown(f"#### {_day(day)}", unsafe_allow_html=True)
        cols = st.columns(3)
        r: Any  # see _recent_results
        for i, r in enumerate(group.itertuples()):
            cols[i % 3].markdown(prediction_card(r, r.tip_label), unsafe_allow_html=True)


def _recent_results(recent: pd.DataFrame) -> pd.DataFrame:
    rows = []
    # pandas-stubs type each itertuples field as any scalar; the columns are
    # only known at runtime.
    r: Any
    for r in recent.itertuples():
        # A coin flip is a home pick - the card's favorite and the accuracy
        # KPI (predictions.prediction_track_record) use the same rule.
        home_pick = float(r.win_probability) >= HOME_PICK_THRESHOLD
        pick = r.home if home_pick else r.away
        pick_pct = _split(r.win_probability)[0 if home_pick else 1]
        home_won = r.home_pts > r.away_pts
        winner = r.home if home_won else r.away
        hi, lo = max(r.home_pts, r.away_pts), min(r.home_pts, r.away_pts)
        rows.append(
            {
                "Date": _day(pd.Timestamp(r.game_date)),
                "Matchup": f"{r.away} @ {r.home}",
                "Pick": f"{pick} {pick_pct}%",
                "Final": f"{winner} {hi}-{lo}",
                "Correct": "✓" if r.correct else "✗",
            }
        )
    return pd.DataFrame(rows)


def _track_record(upcoming: pd.DataFrame) -> None:
    st.markdown("#### Track record", unsafe_allow_html=True)
    record = predictions.prediction_track_record()
    if record.get("n", 0) == 0:
        if upcoming.empty:
            st.info(
                "No predictions have been settled yet. Check back after the first games are played."
            )
        else:
            first = _upcoming(upcoming).iloc[0]["day_et"]
            st.info(f"The first predictions settle after opening night ({_day(first)}).")
        return

    c1, c2, c3 = st.columns(3)
    c1.markdown(
        T.kpi(
            "Accuracy",
            f"{record['accuracy'] * 100:.1f}%",
            f"over {record['n']} games",
            help=glossary.TERMS["Accuracy"],
        ),
        unsafe_allow_html=True,
    )
    c2.markdown(
        T.kpi(
            "Brier score",
            f"{record['brier']:.3f}",
            "lower is better; 0.25 is a coin flip",
            help=glossary.TERMS["Brier score"],
        ),
        unsafe_allow_html=True,
    )
    c3.markdown(
        T.kpi(
            "Margin error",
            f"{record['margin_mae']:.1f}",
            "average points off",
            help=glossary.TERMS["Margin error"],
        ),
        unsafe_allow_html=True,
    )

    bins = stats.calibration_bins(predictions.settled_predictions())
    if not bins.empty:
        st.markdown(
            f"#### Calibration{T.tip(glossary.TERMS['Calibration'])}", unsafe_allow_html=True
        )
        st.caption("When the model gave the home team a chance, how often it won.")
        st.plotly_chart(viz.calibration_chart(bins), config=viz.PLOTLY_CONFIG, width="stretch")

    recent = predictions.recent_settled_predictions()
    if not recent.empty:
        st.markdown("#### Recent results")
        grid = _recent_results(recent)
        st.dataframe(
            grid,
            hide_index=True,
            width="stretch",
            row_height=38,
            # Tall enough for every row: a short list should not scroll.
            height=38 * (len(grid) + 1) + 3,
            column_config={"Correct": st.column_config.TextColumn("Correct", width="small")},
        )


def render() -> None:
    st.markdown("## Predictions", unsafe_allow_html=True)

    if not predictions.predictions_available():
        st.info(
            "No predictions have been published yet. They are written once a "
            "week, before the games are played."
        )
        return

    st.caption(
        "Each card shows the model's chance of a win for either team and the "
        "margin it expects the favorite to win by."
    )

    upcoming = predictions.upcoming_predictions()
    if upcoming.empty:
        st.info("No upcoming games on the schedule right now.")
    else:
        _upcoming_section(upcoming)
    _how_it_works()
    _track_record(upcoming)
