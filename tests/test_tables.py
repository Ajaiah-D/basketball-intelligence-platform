"""lib/tables.py (site-styled HTML tables) and the Games page box score
built on it."""

import pandas as pd

from dashboard.lib import media, tables
from dashboard.lib.tables import Col
from dashboard.views import games


def test_html_table_escapes_text_and_applies_classes():
    df = pd.DataFrame({"name": ["<b>Ann</b>", "Bo"], "pm": [4, -2]})
    out = tables.html_table(
        df,
        [Col("name", "Name", left=True), Col("pm", "+/-", fmt=tables.signed, css=tables.pos_neg)],
    )
    assert "&lt;b&gt;Ann&lt;/b&gt;" in out and "<b>Ann</b>" not in out
    assert '<td class="pos">+4</td>' in out and '<td class="neg">-2</td>' in out
    assert '<th class="lft">Name</th>' in out
    assert 'class="bip-table-wrap"' in out


def test_html_table_totals_row_and_header_help():
    df = pd.DataFrame({"a": [1, 2]})
    out = tables.html_table(df, [Col("a", "A", help="Just a column.")], foot={"a": "3"})
    assert '<tr class="bip-foot"><td>3</td></tr>' in out
    assert "Just a column." in out  # the hover tip in the header


def test_signed_and_pos_neg():
    assert [tables.signed(v) for v in (5, -3, 0, float("nan"))] == ["+5", "-3", "0", "-"]
    assert [tables.pos_neg(v) for v in (5, -3, 0)] == ["pos", "neg", ""]


def _box() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "team": "BOS",
            "team_id": 1610612738,
            "player": ["Star", "Role", "Benchwarmer"],
            "min": [36, 24, 0],
            "pts": [30, 8, 0],
            "reb": [5, 6, 0],
            "ast": [7, 1, 0],
            "stl": [1, 0, 0],
            "blk": [0, 2, 0],
            "tov": [3, 1, 0],
            "fgm": [11, 3, 0],
            "fga": [20, 7, 0],
            "tpm": [4, 0, 0],
            "tpa": [9, 2, 0],
            "ftm": [4, 2, 0],
            "fta": [4, 2, 0],
            "plus_minus": [12, -3, 0],
        }
    )


def test_box_score_card(monkeypatch):
    monkeypatch.setattr(media, "team_logo_data_uri", lambda tid: None)
    out = games.box_score_html(_box(), "BOS", "Home", 113, won=True)
    assert '<td class="hi">30</td>' in out  # the team's top scorer
    assert "11-20" in out and "4-9" in out  # made-attempted
    assert "14-27" in out and "51.9%" in out  # team FG total and percentage
    assert "Did not play: Benchwarmer" in out
    assert out.count("<tr") == 1 + 2 + 1  # header, two who played, totals
    assert 'class="sc winner">113' in out
