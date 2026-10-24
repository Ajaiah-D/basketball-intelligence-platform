"""dashboard/lib/diagnosis.py: the profile stats and the ten areas of the
player breakdown, with how each player measure prints."""

import pandas as pd
import pytest

from dashboard.lib import diagnosis as D
from dashboard.lib import glossary

AREAS = {a.key: a for a in D.AREAS}


# --- Profile stats -----------------------------------------------------------------


def test_profile_stats_follow_the_spec_order_and_groups():
    groups = [s.group for s in D.PROFILE_STATS]
    assert groups == ["Offense"] * 8 + ["Defense"] * 6 + ["Style"]
    keys = [s.key for s in D.PROFILE_STATS]
    assert keys[:3] == ["offensive_rating", "effective_fg_pct", "three_pt_pct"]
    assert keys[8] == "defensive_rating"
    assert keys[-1] == "pace"
    assert len(set(keys)) == len(keys)
    assert set(D.PROFILE_BY_KEY) == set(keys)


def test_every_profile_stat_has_a_glossary_term():
    for stat in D.PROFILE_STATS:
        assert stat.term in glossary.TERMS, stat.key


def test_volume_stats_are_never_judged():
    unjudged = [s.key for s in D.PROFILE_STATS if not s.judged]
    assert unjudged == ["three_pt_rate", "pace"]


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
    for area in D.AREAS:
        assert area.team_stat in D.PROFILE_BY_KEY, area.key
        assert area.team_rank_col == f"{area.team_stat}_rank"
        assert area.measures, area.key
        assert area.caption.endswith("."), area.key


def test_every_measure_has_a_glossary_term_and_a_known_format():
    for area in D.AREAS:
        for m in area.measures:
            assert m.term in glossary.TERMS, (area.key, m.col)
            assert m.kind in {"pct", "share", "ratio", "num", "signed"}, m.col


def test_the_defensive_areas_name_the_limits_of_box_scores():
    defensive = [a.key for a in D.AREAS if a.defensive]
    assert defensive == ["defensive_rebounding", "disruption", "on_off", "fouling"]
    for key in defensive:
        assert "film" in AREAS[key].caption, key
    assert "estimate" in AREAS["on_off"].caption.lower()
    assert "1996-97" in AREAS["on_off"].caption


def test_captions_explain_method_without_a_verdict():
    # Evidence, not verdicts: the captions say how a measure is built and
    # where it falls short, never who is good or bad.
    for area in D.AREAS:
        words = area.caption.lower()
        for verdict in ("strength", "weakness", "drives", "best", "worst"):
            assert verdict not in words, (area.key, verdict)


def test_driver_measures_lists_every_player_column_once():
    cols = D.driver_measures()
    assert len(cols) == len(set(cols))
    for area in D.AREAS:
        for m in area.measures:
            assert m.col in cols


@pytest.mark.parametrize(
    ("kind", "value", "shown"),
    [
        ("pct", 57.46, "57.5%"),
        ("share", 0.312, "31.2%"),
        ("ratio", 0.4654, ".465"),
        ("ratio", 1.25, "1.250"),
        ("num", 3.14, "3.1"),
        ("signed", 3.2, "+3.2"),
        ("signed", -5.6, "-5.6"),
    ],
)
def test_measures_print_by_kind(kind, value, shown):
    assert D.Measure("c", "C", "TS%", kind).format(value) == shown


@pytest.mark.parametrize("value", [None, float("nan"), pd.NA])
def test_a_missing_value_prints_as_a_dash(value):
    assert D.Measure("c", "C", "TS%", "pct").format(value) == "-"
    assert D.missing(value)
