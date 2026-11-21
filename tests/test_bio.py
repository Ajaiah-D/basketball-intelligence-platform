"""dashboard/lib/bio.py and dashboard/lib/defense_metrics.py: the bio line's
formatting, the position filter's matching and the defense ranking."""

from datetime import date

import pandas as pd

from dashboard.lib import bio
from dashboard.lib import defense_metrics as dm


def _bio(**overrides) -> dict:
    base = {
        "position": "G-F",
        "height": "6-6",
        "weight": 220,
        "birthdate": date(1998, 3, 4),
        "country": "USA",
        "college": "Duke",
        "draft_year": 2017,
        "draft_round": 1,
        "draft_number": 3,
    }
    return base | overrides


def test_height_text():
    assert bio.height_text("6-6") == "6'6\""
    assert bio.height_text("7-0") == "7'0\""
    assert bio.height_text(None) is None
    assert bio.height_text("") is None


def test_draft_text():
    assert bio.draft_text(2017, 1, 3) == "2017 R1 #3"
    assert bio.draft_text(None, None, None) == "Undrafted"
    # A draft year without a pick (very old records) still names the year.
    assert bio.draft_text(1980, None, None) == "1980 draft"


def test_bio_line_full():
    assert bio.bio_line(_bio(), 27) == (
        "G-F · 6'6\" · 220 lb · Age 27 · Born Mar 4, 1998 · USA · Duke · 2017 R1 #3"
    )


def test_bio_line_skips_missing_fields():
    line = bio.bio_line(
        _bio(college=None, draft_year=None, draft_round=None, draft_number=None), None
    )
    assert line == "G-F · 6'6\" · 220 lb · Born Mar 4, 1998 · USA · Undrafted"


def test_bio_line_accepts_pandas_missing_values():
    line = bio.bio_line(_bio(weight=float("nan"), birthdate=pd.NaT, country=None), 30)
    assert "lb" not in line and "Born" not in line and "Age 30" in line


def test_age_now():
    assert bio.age_now(date(1998, 3, 4), date(2026, 3, 3)) == 27
    assert bio.age_now(date(1998, 3, 4), date(2026, 3, 4)) == 28
    assert bio.age_now(None, date(2026, 1, 1)) is None


def test_position_matches():
    assert bio.position_matches("G-F", ["F"])
    assert bio.position_matches("G-F", ["G"])
    assert bio.position_matches("F-C", ["G", "C"])
    assert not bio.position_matches("C", ["G"])
    assert bio.position_matches(None, [])
    assert not bio.position_matches(None, ["G"])
    assert bio.position_matches("G", [])


def test_defense_percentiles_reverse_lower_is_better():
    pool = pd.DataFrame({"d_fg_pct_diff": [-5.0, 0.0, 5.0], "deflections_per_36": [1.0, 2.0, 3.0]})
    row = pd.Series({"d_fg_pct_diff": -5.0, "deflections_per_36": 3.0})
    got = {label: pct for label, pct, _ in dm.defense_percentiles(row, pool)}
    # Lowest opponent FG% gap of three: nobody is better, so the top.
    assert got["Opp FG% vs normal"] == 100.0
    # Most deflections of three: better than two of them.
    assert round(got["Deflections/36"], 1) == 66.7
    # Metrics the row or pool lacks are left out, not ranked as zero.
    assert set(got) == {"Opp FG% vs normal", "Deflections/36"}


def test_lower_is_better_labels():
    assert dm.LOWER_IS_BETTER == ["Opp FG% vs normal", "Rim FG% allowed", "Def rating", "On/off"]


def test_missing_sources():
    assert dm.missing_sources("2010-11") == [
        "Defender tracking starts in 2013-14.",
        "Hustle stats start in 2016-17.",
    ]
    assert dm.missing_sources("2014-15") == ["Hustle stats start in 2016-17."]
    assert dm.missing_sources("2020-21") == []


def test_on_off_note():
    has_it = pd.Series({"def_on_minus_off": -1.5, "minutes": 900})
    assert dm.on_off_note(has_it, "2024-25") is None
    early = pd.Series({"def_on_minus_off": None, "minutes": 312.6})
    assert (
        dm.on_off_note(early, "2026-27")
        == "On/off appears once he reaches 500 minutes (he has 312)."
    )
    old_traded = pd.Series({"def_on_minus_off": float("nan"), "minutes": 1800})
    assert "starts in 2007-08" in dm.on_off_note(old_traded, "2003-04")
    assert dm.on_off_note(old_traded, "2015-16") == "No on/off for him this season."
