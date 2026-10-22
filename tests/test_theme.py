from dashboard.lib import theme as T


def test_kpi_note_sits_in_the_label_row_not_a_new_line():
    """A short qualifier ("latest season") rides on the label line so the
    card stays the same height as its neighbours; `sub` is the extra line."""
    html = T.kpi("Play-by-play games", "20", note="latest season")
    assert '<span class="bip-kpi-note">latest season</span>' in html
    assert "bip-kpi-sub" not in html


def test_rgba_turns_a_hex_token_into_a_css_colour():
    assert T.rgba("#3987e5", 0.45) == "rgba(57,135,229,0.45)"
    assert T.rgba(T.CRITICAL, 0.2) == "rgba(208,59,59,0.2)"
