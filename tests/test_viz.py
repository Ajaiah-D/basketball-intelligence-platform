"""Regression tests for dashboard/lib/viz.py chart construction.

team_finances_trend is the one chart in this file whose correctness is a
factual claim, not a style choice: a payroll figure Basketball-Reference's
own source data can't actually back (payroll_likely_incomplete) must never
render as a real low value on a public dashboard. These tests pin that
behavior directly against the pure chart function - no warehouse or
Streamlit needed, since it only takes plain DataFrames.
"""

import math

import pandas as pd

from dashboard.lib import viz


def _team_df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["season", "team_payroll", "payroll_likely_incomplete"])


def _cap_df(seasons: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "season": seasons,
            "salary_cap": [10_000_000] * len(seasons),
            "luxury_tax": [None] * len(seasons),
            "first_apron": [None] * len(seasons),
            "second_apron": [None] * len(seasons),
        }
    )


def test_flagged_season_is_masked_to_a_gap_not_a_low_value():
    team_df = _team_df([
        {"season": "1985-86", "team_payroll": 5_000_000, "payroll_likely_incomplete": False},
        {"season": "1986-87", "team_payroll": 75_000, "payroll_likely_incomplete": True},
        {"season": "1987-88", "team_payroll": 5_500_000, "payroll_likely_incomplete": False},
    ])
    fig = viz.team_finances_trend(team_df, _cap_df(team_df["season"].tolist()))

    payroll_trace = fig.data[0]
    assert payroll_trace.name == "Team payroll"
    assert payroll_trace.connectgaps is False
    assert math.isnan(payroll_trace.y[1]), (
        "the flagged row's raw $75,000 must not reach the chart as a real value"
    )
    assert payroll_trace.y[0] == 5_000_000
    assert payroll_trace.y[2] == 5_500_000


def test_fully_flagged_team_renders_a_placeholder_not_an_empty_chart():
    team_df = _team_df([
        {"season": "1984-85", "team_payroll": 3_500_000, "payroll_likely_incomplete": True},
    ])
    fig = viz.team_finances_trend(team_df, _cap_df(team_df["season"].tolist()))

    # _empty() draws one annotation and no data traces - a franchise whose
    # only season on record is flagged (a real case in this data: KCK) must
    # say why rather than show a blank axis box.
    assert len(fig.data) == 0
    assert len(fig.layout.annotations) == 1
    assert "incomplete" in fig.layout.annotations[0].text.lower()


def test_trend_labels_each_era_and_marks_the_boundary():
    team_df = _team_df([
        {"season": s, "team_payroll": 50_000_000, "payroll_likely_incomplete": False}
        for s in ["2006-07", "2007-08", "2008-09"]
    ])
    eras = [("2006-07", "2007-08", "Seattle SuperSonics"),
            ("2008-09", "2008-09", "Oklahoma City Thunder")]
    fig = viz.team_finances_trend(team_df, _cap_df(team_df["season"].tolist()), eras=eras)
    texts = [a.text for a in fig.layout.annotations]
    assert texts == ["Seattle SuperSonics", "Oklahoma City Thunder"]
    assert len(fig.layout.shapes) == 1 and fig.layout.shapes[0].x0 == "2008-09"


def test_trend_with_one_era_draws_no_labels():
    team_df = _team_df([
        {"season": "2008-09", "team_payroll": 50_000_000, "payroll_likely_incomplete": False},
    ])
    fig = viz.team_finances_trend(team_df, _cap_df(["2008-09"]),
                                  eras=[("2008-09", "2008-09", "Oklahoma City Thunder")])
    assert len(fig.layout.annotations) == 0
    assert len(fig.layout.shapes) == 0


def test_league_snapshot_puts_the_highest_payroll_on_top():
    df = pd.DataFrame({
        "team_name": ["A", "B", "C"], "team_payroll": [150e6, 200e6, 120e6],
        "bar_color": ["#111111"] * 3, "salary_cap": [140e6] * 3,
        "luxury_tax": [170e6] * 3, "first_apron": [None] * 3, "second_apron": [None] * 3,
    })
    fig = viz.league_payroll_snapshot(df, highlight="B")
    bars = fig.data[0]
    # Plotly draws the last category at the top of a horizontal bar chart.
    assert list(bars.y) == ["C", "A", "B"]
    assert {t.name for t in fig.data[1:]} == {"Salary cap", "Luxury tax"}
    assert list(bars.marker.line.width) == [0, 0, 2]


def test_league_snapshot_with_no_rows_says_so():
    empty = pd.DataFrame(columns=["team_name", "team_payroll", "bar_color", "salary_cap",
                                  "luxury_tax", "first_apron", "second_apron"])
    fig = viz.league_payroll_snapshot(empty)
    assert len(fig.data) == 0
    assert "No reliable payroll" in fig.layout.annotations[0].text
