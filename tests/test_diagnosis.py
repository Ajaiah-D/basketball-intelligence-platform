"""dashboard/lib/diagnosis.py: the profile stats, the "Best at / Worst at"
line, the ten "who drives it" areas and the one-line read each of them
writes from small hand-made frames."""

import math

import pandas as pd
import pytest

from dashboard.lib import diagnosis as D
from dashboard.lib import glossary

AREAS = {a.key: a for a in D.AREAS}


# --- Profile stats and the summary line -------------------------------------------


def test_profile_stats_follow_the_spec_order_and_groups():
    groups = [s.group for s in D.PROFILE_STATS]
    assert groups == ["Offense"] * 8 + ["Defense"] * 6 + ["Style"]
    keys = [s.key for s in D.PROFILE_STATS]
    assert keys[:3] == ["offensive_rating", "effective_fg_pct", "three_pt_pct"]
    assert keys[8] == "defensive_rating"
    assert keys[-1] == "pace"
    assert len(set(keys)) == len(keys)


def test_every_profile_stat_has_a_glossary_term():
    for stat in D.PROFILE_STATS:
        assert stat.term in glossary.TERMS, stat.key


def _profile_row(**ranks):
    """A mart_team_profile row with every profile stat ranked 15 unless
    given, and its value set to the rank (the line only reads ranks)."""
    row = {}
    for stat in D.PROFILE_STATS:
        rank = ranks.get(stat.key, 15)
        row[stat.key] = None if rank is None else float(rank)
        row[f"{stat.key}_rank"] = rank
    return pd.Series(row)


def test_summary_line_names_the_three_best_and_three_worst():
    row = _profile_row(
        three_pt_pct=2,
        defensive_rating=4,
        offensive_rating=5,
        turnover_pct=30,
        assist_pct=28,
        opp_free_throw_rate=27,
    )
    assert D.summary_line(row) == (
        "Best at: 3P% (#2), defensive rating (#4), offensive rating (#5)"
        " · Worst at: turnover rate (#30), assist rate (#28), opp FT rate (#27)"
    )


def test_summary_line_ignores_style_and_nulls():
    row = _profile_row(pace=1, three_pt_pct=None, effective_fg_pct=3)
    line = D.summary_line(row)
    assert "pace" not in line.lower()
    assert "3P%" not in line
    assert line.startswith("Best at: eFG% (#3)")


def test_summary_line_breaks_rank_ties_in_profile_order():
    # Everything ties at 15, so the profile's own order decides.
    line = D.summary_line(_profile_row())
    assert line.startswith("Best at: offensive rating (#15), eFG% (#15), 3P% (#15)")
    assert line.endswith(
        "Worst at: opp FT rate (#15), def. rebound % (#15), opp turnover rate (#15)"
    )


def test_summary_line_is_empty_without_data():
    assert D.summary_line(_profile_row(**{s.key: None for s in D.PROFILE_STATS})) == ""
    assert D.summary_line(pd.Series(dtype=object)) == ""
    assert D.summary_line(None) == ""


def test_summary_line_with_few_stats_does_not_repeat_one():
    ranks = {s.key: None for s in D.PROFILE_STATS}
    ranks.update(offensive_rating=3, defensive_rating=20)
    assert D.summary_line(_profile_row(**ranks)) == (
        "Best at: offensive rating (#3) · Worst at: defensive rating (#20)"
    )
    only = {s.key: None for s in D.PROFILE_STATS} | {"offensive_rating": 3}
    assert D.summary_line(_profile_row(**only)) == "Best at: offensive rating (#3)"


# --- Areas --------------------------------------------------------------------------


def test_all_ten_areas_are_defined_with_profile_stats():
    assert [a.label for a in D.AREAS] == [
        "Scoring efficiency",
        "3-point shooting",
        "Ball security",
        "Offensive rebounding",
        "Defensive rebounding",
        "Getting to the line",
        "Playmaking",
        "Disruption",
        "Defense on/off (estimate)",
        "Fouling",
    ]
    profile_keys = {s.key for s in D.PROFILE_STATS}
    for area in D.AREAS:
        assert area.team_stat in profile_keys, area.key
        assert area.team_rank_col == f"{area.team_stat}_rank"
        assert area.player_cols, area.key
        assert area.caption.endswith("."), area.key


def test_the_defensive_areas_say_box_scores_are_not_film():
    defensive = [a.key for a in D.AREAS if a.defensive]
    assert defensive == ["defensive_rebounding", "disruption", "on_off", "fouling"]
    for key in defensive:
        assert "film" in AREAS[key].caption, key
    assert "estimate" in AREAS["on_off"].caption


def test_driver_measures_lists_every_player_column_once():
    cols = D.driver_measures()
    assert len(cols) == len(set(cols))
    for area in D.AREAS:
        for col, _label, _higher in area.player_cols:
            assert col in cols


# --- driver_read --------------------------------------------------------------------


def _rows(players, **medians):
    """A team_drivers()-shaped frame: one dict per player plus the league
    median columns, constant on every row."""
    df = pd.DataFrame(players)
    for col, value in medians.items():
        df[f"{col}_league_median"] = value
    return df


def _check(read):
    assert read.endswith(".")
    assert len(read.split()) <= 25, read
    return read


def test_three_point_read_names_the_volume_and_compares_to_the_median():
    rows = _rows(
        [
            {"player": "Jayson Tatum", "team_three_pa_share": 0.30, "fg3_pct": 37.4},
            {"player": "Jaylen Brown", "team_three_pa_share": 0.22, "fg3_pct": 38.1},
            {"player": "Al Horford", "team_three_pa_share": 0.10, "fg3_pct": 33.0},
        ],
        fg3_pct=35.5,
    )
    assert _check(D.driver_read(AREAS["three_point"], "BOS", rows)) == (
        "Most of BOS's threes come from Tatum and Brown (52% of attempts), "
        "both above league median at 37%+."
    )


def test_three_point_read_does_not_say_most_under_half():
    rows = _rows(
        [
            {"player": "A One", "team_three_pa_share": 0.20, "fg3_pct": 31.0},
            {"player": "B Two", "team_three_pa_share": 0.15, "fg3_pct": 39.0},
            {"player": "C Three", "team_three_pa_share": 0.15, "fg3_pct": 30.0},
        ],
        fg3_pct=35.5,
    )
    read = _check(D.driver_read(AREAS["three_point"], "BOS", rows))
    assert not read.startswith("Most")
    # B Two and C Three tie on share; the name breaks it.
    assert read == (
        "BOS's most frequent three-point shooters are One and Two (35% of attempts), "
        "One below and Two above the league median (35.5%)."
    )


def test_three_point_read_when_both_are_below():
    rows = _rows(
        [
            {"player": "A One", "team_three_pa_share": 0.40, "fg3_pct": 31.0},
            {"player": "B Two", "team_three_pa_share": 0.20, "fg3_pct": 33.0},
        ],
        fg3_pct=35.5,
    )
    assert _check(D.driver_read(AREAS["three_point"], "NYK", rows)) == (
        "Most of NYK's threes come from One and Two (60% of attempts), "
        "both below the league median (35.5%)."
    )


@pytest.mark.parametrize(
    ("key", "col", "values", "median", "expected"),
    [
        (
            "scoring",
            "true_shooting_pct",
            [61.2, 57.0, 55.4],
            57.1,
            "Tatum has BOS's highest true shooting (61.2%; median 57.1%); "
            "1 of 3 regulars beat the league median.",
        ),
        (
            "ball_security",
            "turnover_pct",
            [12.0, 8.1, 10.0],
            11.0,
            "Brown has BOS's lowest turnover rate (8.1%; median 11.0%); "
            "2 of 3 regulars beat the league median.",
        ),
        (
            "offensive_rebounding",
            "offensive_rebound_pct",
            [2.0, 3.5, 11.4],
            4.2,
            "Horford has BOS's highest offensive rebound rate (11.4%; median 4.2%); "
            "1 of 3 regulars beat the league median.",
        ),
        (
            "free_throws",
            "free_throw_rate",
            [0.301, 0.412, 0.150],
            0.250,
            "Brown has BOS's highest free throw rate (.412; median .250); "
            "2 of 3 regulars beat the league median.",
        ),
        (
            "playmaking",
            "assist_pct",
            [25.0, 18.0, 12.0],
            14.0,
            "Tatum has BOS's highest assist rate (25.0%; median 14.0%); "
            "2 of 3 regulars beat the league median.",
        ),
    ],
)
def test_single_measure_reads(key, col, values, median, expected):
    names = ["Jayson Tatum", "Jaylen Brown", "Al Horford"]
    rows = _rows([{"player": n, col: v} for n, v in zip(names, values, strict=True)])
    rows[f"{col}_league_median"] = median
    assert _check(D.driver_read(AREAS[key], "BOS", rows)) == expected


def test_defensive_rebounding_read_calls_itself_an_estimate():
    rows = _rows(
        [
            {"player": "Al Horford", "defensive_rebound_pct": 21.0},
            {"player": "Derrick White", "defensive_rebound_pct": 11.0},
        ],
        defensive_rebound_pct=15.0,
    )
    assert _check(D.driver_read(AREAS["defensive_rebounding"], "BOS", rows)) == (
        "Horford has BOS's highest defensive rebound rate (21.0%; median 15.0%); "
        "1 of 2 regulars beat the league median - a box-score estimate of defense."
    )


def test_disruption_read_names_both_leaders():
    rows = _rows(
        [
            {"player": "Derrick White", "steal_pct": 1.9, "block_pct": 2.4},
            {"player": "Luke Kornet", "steal_pct": 1.0, "block_pct": 4.5},
            {"player": "Jrue Holiday", "steal_pct": 1.9, "block_pct": 0.9},
        ],
        steal_pct=1.5,
        block_pct=1.6,
    )
    # White and Holiday tie on steals; the name breaks it.
    assert _check(D.driver_read(AREAS["disruption"], "BOS", rows)) == (
        "White leads BOS in steal rate (1.9%; median 1.5%), "
        "Kornet in block rate (4.5%; median 1.6%) - a box-score estimate of defense."
    )


def test_three_point_read_with_one_shooter():
    rows = _rows(
        [{"player": "Jayson Tatum", "team_three_pa_share": 0.55, "fg3_pct": 37.4}],
        fg3_pct=35.5,
    )
    assert _check(D.driver_read(AREAS["three_point"], "BOS", rows)) == (
        "Most of BOS's threes come from Tatum (55% of attempts), above the league median at 37.4%."
    )


def test_on_off_read_names_the_biggest_gain():
    rows = _rows(
        [
            {"player": "Jrue Holiday", "def_on_minus_off": -4.6},
            {"player": "Jaylen Brown", "def_on_minus_off": 3.5},
            {"player": "Al Horford", "def_on_minus_off": -3.5},
            {"player": "Traded Guy", "def_on_minus_off": None},
        ],
        def_on_minus_off=0.0,
    )
    assert _check(D.driver_read(AREAS["on_off"], "BOS", rows)) == (
        "BOS defends 4.6 points per 100 better with Holiday on the floor - an estimate; "
        "see the caption."
    )


def test_on_off_read_does_not_overclaim_a_small_gap():
    rows = _rows(
        [
            {"player": "A One", "def_on_minus_off": -0.6},
            {"player": "B Two", "def_on_minus_off": 2.0},
        ],
        def_on_minus_off=0.0,
    )
    assert _check(D.driver_read(AREAS["on_off"], "BOS", rows)) == (
        "No BOS player improves its defense by a point per 100 or more "
        "- an estimate; see the caption."
    )


def test_on_off_read_explains_a_missing_estimate():
    rows = _rows([{"player": "A One", "def_on_minus_off": None}], def_on_minus_off=None)
    assert _check(D.driver_read(AREAS["on_off"], "BOS", rows)) == (
        "No BOS player has an on/off estimate this season; it needs 500+ minutes "
        "for one team, from 1996-97."
    )


def test_fouling_read_names_the_lowest_rate():
    rows = _rows(
        [
            {"player": "Luke Kornet", "fouls_per_36": 3.14},
            {"player": "Al Horford", "fouls_per_36": 1.76},
            {"player": "Jrue Holiday", "fouls_per_36": 1.91},
        ],
        fouls_per_36=2.6,
    )
    assert _check(D.driver_read(AREAS["fouling"], "BOS", rows)) == (
        "Horford has BOS's lowest fouls per 36 (1.8; median 2.6); "
        "2 of 3 regulars beat the league median - a box-score estimate of defense."
    )


@pytest.mark.parametrize("key", [a.key for a in D.AREAS])
def test_every_area_falls_back_when_the_data_is_thin(key):
    area = AREAS[key]
    empty = _rows([{"player": "A One"}])
    for col, _label, _higher in area.player_cols:
        empty[col] = math.nan
        empty[f"{col}_league_median"] = math.nan
    empty["team_three_pa_share"] = math.nan
    read = _check(D.driver_read(area, "BOS", empty))
    assert "BOS" in read
    assert _check(D.driver_read(area, "BOS", empty.iloc[0:0])) == read


def test_short_names_keep_suffixes_and_avoid_clashes():
    assert D._short_names(["Jayson Tatum", "Jaren Jackson Jr."]) == ["Tatum", "Jackson Jr."]
    assert D._short_names(["Jrue Holiday", "Aaron Holiday"]) == ["Jrue Holiday", "Aaron Holiday"]
    assert D._short_names(["Nenê"]) == ["Nenê"]


def test_reads_name_regulars_not_a_few_minutes_of_luck():
    rows = _rows(
        [
            {"player": "Jayson Tatum", "minutes_per_game": 36.0, "free_throw_rate": 0.300},
            {"player": "Jaden Springer", "minutes_per_game": 4.0, "free_throw_rate": 0.422},
            {"player": "Al Horford", "minutes_per_game": 26.0, "free_throw_rate": 0.100},
        ],
        free_throw_rate=0.229,
    )
    assert _check(D.driver_read(AREAS["free_throws"], "BOS", rows)) == (
        "Tatum has BOS's highest free throw rate (.300; median .229); 1 of 2 regulars beat the league median."
    )
    # With nobody at 15 minutes a game, everyone counts.
    rows["minutes_per_game"] = 5.0
    assert D.driver_read(AREAS["free_throws"], "BOS", rows).startswith("Springer has")


def test_disruption_read_names_one_player_once():
    rows = _rows(
        [
            {"player": "Mitchell Robinson", "steal_pct": 2.7, "block_pct": 6.0},
            {"player": "Josh Hart", "steal_pct": 1.9, "block_pct": 0.9},
        ],
        steal_pct=1.5,
        block_pct=1.5,
    )
    assert _check(D.driver_read(AREAS["disruption"], "NYK", rows)) == (
        "Robinson leads NYK in steal rate (2.7%; median 1.5%) and block rate "
        "(6.0%; median 1.5%) - a box-score estimate of defense."
    )
    rows["block_pct_league_median"] = None
    assert _check(D.driver_read(AREAS["disruption"], "NYK", rows)) == (
        "Robinson leads NYK in steal rate (2.7%; median 1.5%) - a box-score estimate of defense."
    )


def test_volume_stats_are_never_judged():
    unjudged = [s.key for s in D.PROFILE_STATS if not s.judged]
    assert unjudged == ["three_pt_rate", "pace"]
    for rank in (1, 30):
        line = D.summary_line(_profile_row(three_pt_rate=rank, pace=rank))
        assert "3-pt rate" not in line, rank
        assert "pace" not in line.lower(), rank


def test_most_of_is_decided_on_the_exact_share():
    # 0.248 + 0.248 = 49.6%: prints as 50% but is not "most".
    rows = _rows(
        [
            {"player": "A One", "team_three_pa_share": 0.248, "fg3_pct": 40.0},
            {"player": "B Two", "team_three_pa_share": 0.248, "fg3_pct": 39.0},
        ],
        fg3_pct=35.5,
    )
    read = _check(D.driver_read(AREAS["three_point"], "BOS", rows))
    assert read.startswith("BOS's most frequent three-point shooters are One and Two (50%")


def test_ball_security_names_a_primary_handler():
    rows = _rows(
        [
            {"player": "Sam Hauser", "turnover_pct": 4.6, "usage_pct": 12.0},
            {"player": "Jayson Tatum", "turnover_pct": 11.2, "usage_pct": 30.1},
            {"player": "Jaylen Brown", "turnover_pct": 13.0, "usage_pct": 28.0},
        ],
        turnover_pct=11.9,
    )
    assert _check(D.driver_read(AREAS["ball_security"], "BOS", rows)) == (
        "Of BOS's high-usage players (20%+), Tatum has the lowest turnover rate "
        "(11.2%; median 11.9%); 2 of 3 regulars beat the league median."
    )
    # Nobody at 20% usage: the general sentence.
    rows["usage_pct"] = 15.0
    assert _check(D.driver_read(AREAS["ball_security"], "BOS", rows)) == (
        "Hauser has BOS's lowest turnover rate (4.6%; median 11.9%); "
        "2 of 3 regulars beat the league median."
    )
