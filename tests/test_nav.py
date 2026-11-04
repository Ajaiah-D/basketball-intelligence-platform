"""dashboard/lib/nav.py: the page registry app.py fills and views switch
through."""

from pathlib import Path

import pytest
import streamlit as st

from dashboard.lib import nav


def test_go_switches_to_the_registered_page(monkeypatch):
    sent: list = []
    monkeypatch.setattr(nav, "_PAGES", {})
    monkeypatch.setattr(st, "switch_page", sent.append)
    nav.register("players", "players-page")
    nav.go("players")
    assert sent == ["players-page"]


def test_an_unregistered_name_is_a_clear_error(monkeypatch):
    monkeypatch.setattr(nav, "_PAGES", {})
    with pytest.raises(KeyError, match=r"app\.py registers them"):
        nav.go("players")


def test_the_advanced_page_is_no_longer_registered():
    """Advanced stats live on Players and Teams now; /advanced falls through
    to Streamlit's page-not-found handling."""
    root = Path(__file__).resolve().parent.parent / "dashboard"
    app = (root / "app.py").read_text(encoding="utf-8")
    assert '"advanced"' not in app
    assert "advanced.render" not in app
    assert not (root / "views" / "advanced.py").exists()
