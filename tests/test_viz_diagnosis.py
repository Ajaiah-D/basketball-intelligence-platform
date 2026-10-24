"""The diagnosis charts (dashboard/lib/viz_diagnosis.py): the league-ranks
profile and the player breakdown.

Pure: hand-built mart_team_profile rows and rotations, no warehouse or
Streamlit.
"""

import math

import pandas as pd

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
    # Style ranks say what they count, as a plain rank from the top.
    assert texts["pace"] == "104.2 · #1 fastest"
    assert texts["three_pt_rate"] == "40.3% · #29 in threes"


def test_style_hover_counts_the_league():
    row = _row()
    row["pace_rank"] = 22
    hovers = viz_diagnosis.profile_chart(row, league_size=23).data[0].hovertext
    assert any("#22 of 23 fastest" in h for h in hovers)
    assert any("in threes taken" in h for h in hovers)


def test_short_bars_label_outside_on_a_background():
    fig = viz_diagnosis.profile_chart(_row(pctile=10.0))
    trace = fig.data[0]
    bars = [i for i, x in enumerate(trace.x) if x is not None]
    assert all(trace.textposition[i] == "none" for i in bars)
    labels = [a for a in fig.layout.annotations if a.text != "league median"]
    assert len(labels) == len(bars)
    assert all(a.bgcolor and a.xanchor == "left" for a in labels)

    long = viz_diagnosis.profile_chart(_row(pctile=100.0))
    assert all(p == "inside" for p in long.data[0].textposition if p != "none")
    assert [a.text for a in long.layout.annotations] == ["league median"]


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


# --- The player breakdown chart ----------------------------------------------------

AREAS = {a.key: a for a in diagnosis.AREAS}


def _rotation(**overrides) -> pd.DataFrame:
    """Three players, most minutes first, with every area measure and its
    league median."""
    rows = pd.DataFrame(
        {
            "player_id": [1, 2, 3],
            "player": ["Ann Able", "Ben Best", "Cy Cole"],
            "games_played": [70, 60, 12],
            "minutes": [2400.0, 1500.0, 150.0],
        }
    )
    for col in diagnosis.driver_measures():
        rows[col] = [10.0, 20.0, 30.0]
        rows[f"{col}_league_median"] = 18.0
    for col, values in overrides.items():
        rows[col] = values
    return rows


def test_one_dot_per_player_in_minutes_order_in_the_team_colour():
    fig = viz_diagnosis.drivers_chart(_rotation(), AREAS["playmaking"], "OKC")
    assert len(fig.data) == 1
    trace = fig.data[0]
    assert list(trace.y) == ["p1", "p2", "p3"]
    assert list(trace.x) == [10.0, 20.0, 30.0]
    assert trace.marker.color == T.team_color("OKC")
    assert list(fig.layout.yaxis.ticktext) == ["Ann Able", "Ben Best", "Cy Cole"]
    assert fig.layout.yaxis.autorange == "reversed"
    assert fig.layout.yaxis.type == "category"
    assert fig.layout.showlegend is False


def test_dot_size_follows_minutes():
    sizes = list(
        viz_diagnosis.drivers_chart(_rotation(), AREAS["playmaking"], "OKC").data[0].marker.size
    )
    assert sizes == sorted(sizes, reverse=True)
    assert sizes[0] == viz_diagnosis._DOT_MAX_PX
    assert sizes[-1] >= viz_diagnosis._DOT_MIN_PX


def test_a_dashed_median_line_and_label_per_measure():
    fig = viz_diagnosis.drivers_chart(_rotation(), AREAS["scoring"], "BOS")
    # Two measures: two panels on their own x axes, sharing the rows.
    assert [t.xaxis for t in fig.data] == ["x", "x2"]
    assert all(t.yaxis == "y" for t in fig.data)
    lines = [s for s in fig.layout.shapes if s.line.dash == "dash"]
    assert [(s.xref, s.x0) for s in lines] == [("x", 18.0), ("x2", 18.0)]
    labels = [a.text for a in fig.layout.annotations if a.text.startswith("median")]
    assert labels == ["median 18.0%", "median 18.0%"]
    assert fig.layout.xaxis.title.text == "TS%"
    assert fig.layout.xaxis2.title.text == "USG%"
    left, right = fig.layout.xaxis.domain, fig.layout.xaxis2.domain
    assert left[1] < right[0]


def test_the_range_holds_every_value_and_the_median():
    rows = _rotation(assist_pct=[5.0, 6.0, 7.0], assist_pct_league_median=40.0)
    lo, hi = viz_diagnosis.drivers_chart(rows, AREAS["playmaking"], "OKC").layout.xaxis.range
    assert lo < 5.0 and hi > 40.0


def test_a_missing_value_reads_not_available():
    rows = _rotation(def_on_minus_off=[-3.0, None, None])
    fig = viz_diagnosis.drivers_chart(rows, AREAS["on_off"], "OKC")
    notes = [a for a in fig.layout.annotations if a.text == "not available"]
    assert [a.y for a in notes] == ["p2", "p3"]
    assert fig.layout.xaxis.zeroline is True  # on/off is a difference


def test_the_hover_names_the_value_the_median_and_the_glossary():
    fig = viz_diagnosis.drivers_chart(_rotation(), AREAS["fouling"], "OKC")
    hover = fig.data[0].hovertext[0]
    assert "Ann Able" in hover and "Fouls per 36 10.0" in hover
    assert "league median 18.0" in hover
    assert "2,400 min · 70 games for this team" in hover
    assert "Personal fouls per 36" in hover


def test_no_rotation_gives_the_placeholder():
    fig = viz_diagnosis.drivers_chart(_rotation().iloc[0:0], AREAS["fouling"], "OKC")
    assert not fig.data


# --- The any-two-stats scatter -------------------------------------------------------


def _league(n: int = 30) -> pd.DataFrame:
    """n teams with an "off" stat (higher is better) and a "dfn" stat (lower
    is better), each with the 1-n rank the mart would give it."""
    off = [100.0 + i for i in range(n)]
    dfn = [120.0 - 0.5 * i + (i % 3) for i in range(n)]
    df = pd.DataFrame(
        {
            "team_abbreviation": [f"T{i:02d}" for i in range(n)],
            "team_name": [f"Team {i}" for i in range(n)],
            "off": off,
            "dfn": dfn,
        }
    )
    df["off_rank"] = df["off"].rank(ascending=False, method="min").astype(int)
    df["dfn_rank"] = df["dfn"].rank(ascending=True, method="min").astype(int)
    return df


def _scatter(df=None, **kwargs):
    kwargs.setdefault("label_top", 30)
    return viz_diagnosis.stat_scatter(
        _league() if df is None else df,
        "off",
        "dfn",
        "team_abbreviation",
        "team_abbreviation",
        **kwargs,
    )


def test_scatter_draws_one_dot_per_team_and_the_pick_as_its_own_trace():
    fig = _scatter(highlight="T07")
    assert sum(len(t.x) for t in fig.data) == 30
    pick = [t for t in fig.data if list(t.text) == ["T07"] and len(t.x) == 1]
    assert len(pick) == 1
    others = next(t for t in fig.data if t is not pick[0])
    assert len(others.x) == 29
    # Bigger and outlined against the rest, and still in the team's colour.
    assert pick[0].marker.size > others.marker.size
    assert pick[0].marker.line.width > others.marker.line.width
    assert list(pick[0].marker.color) == [T.team_color("T07")]


def test_scatter_dots_take_the_team_colours():
    fig = _scatter(highlight="T07", label_top=40)
    others = fig.data[0]
    codes = [a for a in _league()["team_abbreviation"] if a != "T07"]
    assert list(others.text) == codes
    assert list(others.marker.color) == [T.team_color(a) for a in codes]


def test_scatter_without_a_highlight_has_one_trace():
    fig = _scatter()
    assert len(fig.data) == 1 and len(fig.data[0].x) == 30


def test_scatter_dashed_league_average_lines_at_the_means():
    df = _league()
    fig = _scatter(df)
    dashed = [s for s in fig.layout.shapes if s.line.dash == "dash"]
    xs = [s.x0 for s in dashed if s.x0 == s.x1]
    ys = [s.y0 for s in dashed if s.y0 == s.y1]
    assert xs == [df["off"].mean()] and ys == [df["dfn"].mean()]
    # Only the average is labelled; the quadrants carry no verdicts.
    notes = [a.text for a in fig.layout.annotations]
    assert notes == ["league average"]


def test_scatter_caps_the_labels_but_always_names_the_pick():
    fig = _scatter(highlight="T03", label_top=5)
    labelled = [t for tr in fig.data for t in tr.text if t]
    assert len(labelled) == 5
    assert "T03" in labelled
    # Unlabelled dots keep an empty label, so every dot still has a hover.
    assert len(fig.data[0].text) == 29


def test_scatter_labels_the_dots_furthest_from_the_average():
    df = _league()
    # Both stats run straight along the index, so the ends are furthest.
    df["dfn"] = [120.0 - i for i in range(30)]
    fig = _scatter(df, label_top=2)
    labelled = {t for tr in fig.data for t in tr.text if t}
    assert labelled == {"T00", "T29"}


def test_scatter_inverted_axis_is_reversed_and_says_so():
    fig = _scatter(invert=("dfn",), x_label="Offense", y_label="Defense")
    assert fig.layout.yaxis.autorange == "reversed"
    assert fig.layout.xaxis.autorange is None
    assert "reversed" in fig.layout.yaxis.title.text
    assert fig.layout.yaxis.title.text.startswith("Defense")
    assert fig.layout.xaxis.title.text == "Offense"
    both = _scatter(invert=("off", "dfn"))
    assert both.layout.xaxis.autorange == "reversed"
    assert "reversed" in both.layout.xaxis.title.text


def test_scatter_hover_has_the_team_both_values_and_both_ranks():
    df = _league()
    fig = _scatter(df, name_col="team_name", fmt=lambda key, v: f"{v:.1f}!")
    hover = fig.data[0].hovertext[3]
    assert "Team 3" in hover
    assert "103.0!" in hover
    assert f"#{df['dfn_rank'][3]} of 30" in hover
    assert f"#{df['off_rank'][3]} of 30" in hover
    assert fig.data[0].hovertemplate == "%{hovertext}<extra></extra>"


def test_scatter_without_rank_columns_hovers_values_only():
    df = _league().drop(columns=["off_rank", "dfn_rank"])
    hover = _scatter(df).data[0].hovertext[0]
    assert "#" not in hover and "T00" in hover


def test_scatter_skips_teams_missing_either_stat():
    df = _league()
    df.loc[0, "off"] = math.nan
    df.loc[1, "dfn"] = math.nan
    fig = _scatter(df)
    assert len(fig.data[0].x) == 28


def test_scatter_with_nothing_to_plot_is_a_sentence():
    df = _league()
    df["off"] = math.nan
    fig = _scatter(df)
    assert len(fig.data) == 0 and len(fig.layout.annotations) == 1


def test_scatter_of_a_stat_against_itself_still_draws():
    fig = viz_diagnosis.stat_scatter(
        _league(), "off", "off", "team_abbreviation", "team_abbreviation"
    )
    assert len(fig.data[0].x) == 30


def test_lower_is_better_comes_from_the_ranks():
    df = _league()
    assert viz_diagnosis.lower_is_better(df, "dfn") is True
    assert viz_diagnosis.lower_is_better(df, "off") is False
    assert viz_diagnosis.lower_is_better(df.drop(columns=["dfn_rank"]), "dfn") is False
    assert viz_diagnosis.lower_is_better(df.assign(off=math.nan), "off") is False


def test_scatter_rank_counts_come_from_the_ranking_pool_not_the_plotted_rows():
    # 2 of 30 teams lack "dfn": the 28 plotted still hover "of 30" for the
    # stat that is ranked across all 30.
    df = _league()
    df.loc[[0, 1], "dfn"] = math.nan
    df.loc[[0, 1], "dfn_rank"] = math.nan
    hover = _scatter(df).data[0].hovertext[5]
    assert "of 30" in hover.split("<br>")[1]
    # The stat that lacks values is ranked among the 28 that have one.
    assert "of 28" in hover.split("<br>")[2]


def test_scatter_draws_every_row_matching_the_highlight_in_the_pick_trace():
    df = _league()
    df.loc[4, "team_abbreviation"] = "T07"
    fig = _scatter(df, highlight="T07")
    pick = fig.data[1]
    assert len(pick.x) == 2
    assert sum(len(t.x) for t in fig.data) == 30
