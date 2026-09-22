"""Upcoming game predictions and the model's public track record."""

import streamlit as st

from dashboard.lib import db
from dashboard.lib import theme as T


def render() -> None:
    st.markdown("## Predictions", unsafe_allow_html=True)

    if not db.predictions_available():
        st.info(
            "No predictions have been published yet. They are written once a "
            "week, before the games are played."
        )
        return

    upcoming = db.upcoming_predictions()
    if upcoming.empty:
        st.info("No upcoming games on the schedule right now.")
    else:
        st.caption(
            "Win probability is for the home team. Early in a season no team "
            "has current-season form yet, so these lean almost entirely on "
            "carried-over ratings and are correspondingly less reliable."
        )
        st.dataframe(upcoming, hide_index=True, use_container_width=True)

    st.markdown("#### Track record", unsafe_allow_html=True)
    record = db.prediction_track_record()
    if record.get("n", 0) == 0:
        st.info("No predictions have been settled yet. Check back after the "
                "first games are played.")
        return

    c1, c2, c3 = st.columns(3)
    c1.markdown(T.kpi("Accuracy", f"{record['accuracy'] * 100:.1f}%",
                      f"over {record['n']} games"), unsafe_allow_html=True)
    c2.markdown(T.kpi("Brier score", f"{record['brier']:.3f}",
                      "lower is better; 0.25 is a coin flip"),
                unsafe_allow_html=True)
    c3.markdown(T.kpi("Margin error", f"{record['margin_mae']:.1f}",
                      "average points off"), unsafe_allow_html=True)
