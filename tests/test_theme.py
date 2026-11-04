"""The theme's tokens and the rule that colours live only in theme.py."""

import re
from pathlib import Path

from dashboard.lib import theme as T

ROOT = Path(__file__).resolve().parent.parent
HEX = re.compile(r"#[0-9a-fA-F]{6}\b")


def test_kpi_note_sits_in_the_label_row_not_a_new_line():
    """A short qualifier ("latest season") rides on the label line so the
    card stays the same height as its neighbours; `sub` is the extra line."""
    html = T.kpi("Play-by-play games", "20", note="latest season")
    assert '<span class="bip-kpi-note">latest season</span>' in html
    assert "bip-kpi-sub" not in html


def test_rgba_turns_a_hex_token_into_a_css_colour():
    assert T.rgba("#3987e5", 0.45) == "rgba(57,135,229,0.45)"
    assert T.rgba(T.CRITICAL, 0.2) == "rgba(208,59,59,0.2)"


def test_the_dim_court_tokens():
    assert T.PAGE == "#1d232c"
    assert T.SIDEBAR == "#181d25"
    assert T.SURFACE == "#262d38"
    assert T.SURFACE_2 == "#2f3744"
    assert T.INK == "#f1f4f8"
    assert T.BRAND == "#f08a3c"
    assert T.SERIES[0] == T.ACCENT


def test_no_hex_colour_outside_theme_py():
    offenders = []
    for path in (ROOT / "dashboard").rglob("*.py"):
        if path.name == "theme.py":
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if HEX.search(line):
                offenders.append(f"{path.relative_to(ROOT)}:{n}")
    assert offenders == []


def test_config_toml_mirrors_the_tokens():
    config = (ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8")
    for token in (T.PAGE, T.SURFACE, T.INK, T.BRAND, T.SURFACE_2, T.GRID):
        assert token in config


def test_css_has_no_leftover_near_black_surfaces():
    for old in ("#0d0d0d", "#1a1a19", "#1e1e1d", "#171716", "#1b1b1a", "#101010"):
        assert old not in T.CSS
