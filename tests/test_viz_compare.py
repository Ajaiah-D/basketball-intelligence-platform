"""The Compare tab's charts (dashboard/lib/viz_compare.py): a radar of
percentiles and a per-game stat line.

Pure: hand-built values, no warehouse or Streamlit.
"""

from dashboard.lib import theme as T
from dashboard.lib import viz_compare as vc

AXES = ["Scoring", "Efficiency", "Rebounding", "Playmaking"]


def _side(name="A", color="#112233", values=(90.0, 70.0, 50.0, 30.0)):
    return vc.RadarSide(
        name, color, values, [f"{a} {v:.0f}" for a, v in zip(AXES, values, strict=True)]
    )


def test_radar_closes_each_outline_on_its_first_spoke():
    fig = vc.compare_radar(AXES, [_side(), _side("B", "#445566", (10.0, 20.0, 30.0, 40.0))])
    assert len(fig.data) == 2
    first = fig.data[0]
    assert list(first.theta) == [*AXES, AXES[0]]
    assert list(first.r) == [90.0, 70.0, 50.0, 30.0, 90.0]
    assert first.line.color == "#112233"
    hovers = list(first.customdata)
    assert hovers[-1] == hovers[0]


def test_radar_axis_runs_zero_to_a_hundred_and_marks_no_winner():
    fig = vc.compare_radar(AXES, [_side(), _side("B", "#445566")])
    assert list(fig.layout.polar.radialaxis.range) == [0, 100]
    a, b = fig.data
    # The same tint and line weight on both: neither shape is drawn stronger.
    assert a.line.width == b.line.width
    assert a.fillcolor.endswith("0.18)") and b.fillcolor.endswith("0.18)")


def test_radar_needs_three_spokes_and_a_side():
    assert not vc.compare_radar(AXES[:2], [_side()]).data
    assert not vc.compare_radar(AXES, []).data


def test_radar_draws_a_single_side():
    assert len(vc.compare_radar(AXES, [_side()]).data) == 1


def _stats():
    return [
        vc.BarStat("PTS", (30.0, 15.0), ("30.0", "15.0")),
        vc.BarStat("STL", (1.2, None), ("1.2", "-")),
    ]


def test_bars_have_a_row_per_stat_and_a_bar_per_side_in_its_colour():
    sides = [vc.BarSide("A", "#112233"), vc.BarSide("B", T.ACCENT)]
    fig = vc.compare_bars(_stats(), sides)
    assert len(fig.data) == 4
    assert [t.y[0] for t in fig.data] == ["PTS", "PTS", "STL", "STL"]
    assert [t.marker.color for t in fig.data] == ["#112233", T.ACCENT] * 2
    assert [t.text[0] for t in fig.data] == ["30.0", "15.0", "1.2", "-"]
    # Printed values, every row: the legend shows once.
    assert [t.showlegend for t in fig.data] == [True, True, False, False]


def test_each_row_is_scaled_to_its_own_stat_from_zero():
    fig = vc.compare_bars(_stats(), [vc.BarSide("A", "#112233"), vc.BarSide("B", T.ACCENT)])
    assert fig.layout.xaxis.range[0] == 0 and fig.layout.xaxis2.range[0] == 0
    # Headroom past the longer bar for its printed value; rows differ.
    assert fig.layout.xaxis.range[1] > 30.0
    assert fig.layout.xaxis2.range[1] < fig.layout.xaxis.range[1]
    # A missing value draws no length.
    assert fig.data[3].x[0] == 0


def test_bars_with_nothing_to_show_say_so():
    assert not vc.compare_bars([], [vc.BarSide("A", "#112233")]).data
