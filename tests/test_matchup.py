"""dashboard/lib/matchup.py: the one-line matchup with the model's
favourite marked, shared by the Schedule and Predictions pages."""

import re

from dashboard.lib import matchup
from dashboard.lib import theme as T


def _text(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html)


def test_a_home_favourite_is_bold_in_its_colour_with_one_percentage():
    out = matchup.favourite_matchup_html("NYK", "BOS", 0.65)
    assert _text(out) == "NYK @ BOS · 65%"
    assert f'<b style="color:{T.team_color("BOS")}">BOS</b>' in out
    # Each abbreviation once, the probability once.
    assert out.count("BOS") == 1 and out.count("NYK") == 1
    assert out.count("%") == 1


def test_an_away_favourite_gets_the_away_share():
    out = matchup.favourite_matchup_html("NYK", "BOS", 0.30)
    assert _text(out) == "NYK @ BOS · 70%"
    assert f'<b style="color:{T.team_color("NYK")}">NYK</b>' in out
    assert "<b" not in out.split("@")[1]


def test_under_55_percent_is_a_toss_up_with_no_favourite():
    for p in (0.5, 0.54, 0.46):
        out = matchup.favourite_matchup_html("NYK", "BOS", p)
        assert _text(out) == "NYK @ BOS · toss-up"
        assert "<b" not in out


def test_55_percent_is_a_favourite():
    assert _text(matchup.favourite_matchup_html("NYK", "BOS", 0.55)) == "NYK @ BOS · 55%"
    assert _text(matchup.favourite_matchup_html("NYK", "BOS", 0.45)) == "NYK @ BOS · 55%"


def test_no_prediction_is_the_matchup_alone():
    for p in (None, float("nan")):
        out = matchup.favourite_matchup_html("NYK", "BOS", p)
        assert _text(out) == "NYK @ BOS"
        assert "<b" not in out


def test_text_is_escaped():
    out = matchup.favourite_matchup_html("<A>", "B&B", 0.9)
    assert "&lt;A&gt;" in out and "B&amp;B" in out
    assert "<A>" not in out


def test_tipoff_label_is_eastern_time():
    import pandas as pd

    # 23:00 UTC in late October is 7 PM Eastern (daylight time) ...
    assert matchup.tipoff_label(pd.Timestamp("2026-10-23 23:00:00")) == "7:00 PM ET"
    # ... and in December, standard time, 6 PM.
    assert matchup.tipoff_label(pd.Timestamp("2026-12-01 23:00:00")) == "6:00 PM ET"
    assert matchup.tipoff_label(pd.Timestamp("2026-10-24 02:30:00")) == "10:30 PM ET"
    assert matchup.tipoff_label(pd.Timestamp("2026-10-23 16:05:00")) == "12:05 PM ET"
    assert matchup.tipoff_label(None) == "TBD"
    assert matchup.tipoff_label(pd.NaT) == "TBD"


# --- The Predictions page's split: matchup, chance and margin in their own columns


def test_matchup_html_marks_the_favourite_without_a_percentage():
    out = matchup.matchup_html("NYK", "BOS", 0.65)
    assert _text(out) == "NYK @ BOS"
    assert f'<b style="color:{T.team_color("BOS")}">BOS</b>' in out
    away = matchup.matchup_html("NYK", "BOS", 0.30)
    assert f'<b style="color:{T.team_color("NYK")}">NYK</b>' in away
    for p in (0.52, None, float("nan")):
        assert "<b" not in matchup.matchup_html("NYK", "BOS", p)


def test_chance_is_the_favourites_share_with_a_bar_in_its_colour():
    out = matchup.chance_html("NYK", "BOS", 0.65)
    assert _text(out).strip() == "65%"
    assert T.team_color("BOS") in out
    # 65% sits 30% of the way from a coin flip (50) to a certainty (100).
    assert "width:30%" in out
    assert "toss-up" not in out
    full = matchup.chance_html("NYK", "BOS", 0.0)
    assert _text(full).strip() == "100%" and "width:100%" in full
    assert T.team_color("NYK") in full


def test_under_55_percent_the_bar_is_replaced_by_toss_up():
    out = matchup.chance_html("NYK", "BOS", 0.53)
    assert "53%" in out and "toss-up" in out
    assert "width:" not in out
    assert T.team_color("BOS") not in out and T.team_color("NYK") not in out


def test_no_prediction_is_a_dash():
    assert matchup.chance_html("NYK", "BOS", None) == "-"


def test_margin_label_never_says_by_0():
    assert matchup.margin_label(4.6) == "by 5"
    assert matchup.margin_label(-2.2) == "by 2"
    assert matchup.margin_label(0.1) == "by 1"
    assert matchup.margin_label(None) == "-"
    assert matchup.margin_label(float("nan")) == "-"
