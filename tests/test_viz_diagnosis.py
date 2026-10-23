"""The strengths-and-weaknesses chart (dashboard/lib/viz_diagnosis.py).

Pure: a hand-built mart_team_profile row, no warehouse or Streamlit.
"""

import math

from dashboard.lib import diagnosis, viz_diagnosis
from dashboard.lib import theme as T


def _row(pctile: float = 50.0, rank: int = 15) -> dict:
    """A profile row with every stat at the same value, rank and percentile."""
    row: dict = {}
    for stat in diagnosis.PROFILE_STATS:
        row[stat.key] = 50.0
        row[f"{stat.key}_rank"] = rank
        row[f"{stat.key}_pctile"] = pctile
    return row


def _bars(fig):
    """(category, x, colour, text) for each row that has a bar."""
    trace = fig.data[0]
    return [
        (y, x, c, t)
        for y, x, c, t in zip(trace.y, trace.x, trace.marker.color, trace.text, strict=True)
        if x is not None
    ]


def test_one_bar_per_profile_stat_and_one_label_per_group():
    fig = viz_diagnosis.profile_chart(_row())
    bars = _bars(fig)
    assert [b[0] for b in bars] == [s.key for s in diagnosis.PROFILE_STATS]
    ticks = list(fig.layout.yaxis.ticktext)
    for group in ("OFFENSE", "DEFENSE", "STYLE"):
        assert sum(group in t for t in ticks) == 1
    assert fig.layout.showlegend is False


def test_height_grows_with_the_rows():
    full = viz_diagnosis.profile_chart(_row())
    fewer = _row()
    for stat in diagnosis.PROFILE_STATS[:5]:
        fewer[f"{stat.key}_pctile"] = math.nan
    short = viz_diagnosis.profile_chart(fewer)
    assert len(_bars(short)) == len(diagnosis.PROFILE_STATS) - 5
    assert short.layout.height < full.layout.height


def test_colours_follow_the_percentile_and_style_rows_are_muted():
    judged = [s.key for s in diagnosis.PROFILE_STATS if s.judged]
    unjudged = [s.key for s in diagnosis.PROFILE_STATS if not s.judged]
    for pctile, expected in ((100.0, T.GOOD), (0.0, T.CRITICAL)):
        bars = {b[0]: b[2] for b in _bars(viz_diagnosis.profile_chart(_row(pctile)))}
        assert all(bars[k].lower() == expected.lower() for k in judged)
        assert all(bars[k] == T.MUTED for k in unjudged)

    mid = {b[0]: b[2] for b in _bars(viz_diagnosis.profile_chart(_row(50.0)))}
    assert mid["offensive_rating"] == viz_diagnosis.PROFILE_NEUTRAL
    assert viz_diagnosis.PROFILE_NEUTRAL != T.MUTED


def test_the_scale_runs_red_to_green():
    reds = [viz_diagnosis._hex_rgb(viz_diagnosis.percentile_color(p))[0] for p in (0, 25, 50)]
    greens = [viz_diagnosis._hex_rgb(viz_diagnosis.percentile_color(p))[1] for p in (50, 75, 100)]
    assert reds == sorted(reds, reverse=True)
    assert greens == sorted(greens)


def test_labels_carry_value_and_rank():
    row = _row(pctile=93.1, rank=3)
    row["effective_fg_pct"] = 56.14
    row["offensive_rating"] = 117.6
    row["pace"] = 104.22
    row["pace_rank"] = 1
    row["three_pt_rate"] = 40.3
    row["three_pt_rate_rank"] = 29
    texts = {b[0]: b[3] for b in _bars(viz_diagnosis.profile_chart(row))}
    assert texts["effective_fg_pct"] == "56.1% · #3"
    assert texts["offensive_rating"] == "117.6 · #3"
    assert texts["pace"] == "104.2 · #1 most"
    assert texts["three_pt_rate"] == "40.3% · #2 least"


def test_style_rank_uses_the_league_size():
    row = _row()
    row["pace_rank"] = 22
    texts = {b[0]: b[3] for b in _bars(viz_diagnosis.profile_chart(row, league_size=23))}
    assert texts["pace"].endswith("#2 least")


def test_hover_explains_each_stat():
    hovers = viz_diagnosis.profile_chart(_row()).data[0].hovertext
    assert any("Possessions per 48 minutes" in h for h in hovers)


def test_a_dashed_median_line():
    fig = viz_diagnosis.profile_chart(_row())
    lines = [s for s in fig.layout.shapes if s.x0 == 50 and s.x1 == 50]
    assert len(lines) == 1 and lines[0].line.dash == "dash"


def test_no_ranks_draws_a_sentence_not_an_empty_axis():
    empty = dict.fromkeys(_row(), math.nan)
    fig = viz_diagnosis.profile_chart(empty)
    assert len(fig.data) == 0
    assert len(fig.layout.annotations) == 1
