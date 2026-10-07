"""Player imagery. NBA's CDN hosts headshots keyed by player id; coverage
is complete for modern players and spotty for pre-2000s ones, so every
avatar has an initials fallback rendered in the team color.

Images are fetched server-side and embedded as base64 data URIs: it
sidesteps CDN hotlink/referrer quirks in the browser and the result is
cached by Streamlit for a day."""

from __future__ import annotations

import base64

import requests
import streamlit as st

HEADSHOT_URL = "https://cdn.nba.com/headshots/nba/latest/260x190/{pid}.png"
LOGO_URL = "https://cdn.nba.com/logos/nba/{tid}/global/L/logo.svg"


@st.cache_data(ttl=86400, show_spinner=False, max_entries=512)
def headshot_data_uri(player_id: int) -> str | None:
    """Base64 data URI for the player's headshot, or None if the CDN
    doesn't have one (cached 24h)."""
    url = HEADSHOT_URL.format(pid=int(player_id))
    try:
        r = requests.get(url, timeout=5)
        if r.status_code != 200 or not r.content:
            return None
        b64 = base64.b64encode(r.content).decode()
        return f"data:image/png;base64,{b64}"
    except requests.RequestException:
        return None


@st.cache_data(ttl=86400, show_spinner=False, max_entries=64)
def team_logo_data_uri(team_id: int) -> str | None:
    """Base64 data URI for a team's logo SVG, or None (cached 24h)."""
    try:
        r = requests.get(LOGO_URL.format(tid=int(team_id)), timeout=5)
        if r.status_code != 200 or not r.content:
            return None
        return "data:image/svg+xml;base64," + base64.b64encode(r.content).decode()
    except requests.RequestException:
        return None


def team_logo_html(team_id: int, abbr: str, size: int = 80, color: str = "#3987e5") -> str:
    """Team logo; a team-color disc with the abbreviation if the CDN has none."""
    uri = team_logo_data_uri(team_id)
    if uri:
        return (f'<img src="{uri}" alt="{abbr}" '
                f'style="width:{size}px;height:{size}px;object-fit:contain"/>')
    return (
        f'<span style="display:inline-flex;width:{size}px;height:{size}px;'
        f'border-radius:50%;border:2px solid {color};background:{color}26;'
        f'color:{color};align-items:center;justify-content:center;'
        f'font-weight:800;font-size:{size * 0.3:.0f}px">{abbr}</span>'
    )


def avatar_html(player_id: int, name: str, size: int = 72,
                ring: str = "#3987e5") -> str:
    """Circular headshot with a team-color ring; initials disc fallback."""
    uri = headshot_data_uri(player_id)
    if uri:
        return (
            f'<span style="display:inline-block;width:{size}px;height:{size}px;'
            f'border-radius:50%;border:2px solid {ring};overflow:hidden;'
            f'vertical-align:middle;background:#242423">'
            f'<img src="{uri}" alt="" '
            f'style="width:100%;height:100%;object-fit:cover;object-position:top"/>'
            f'</span>'
        )
    initials = "".join(w[0] for w in name.split()[:2]).upper()
    return (
        f'<span style="display:inline-flex;width:{size}px;height:{size}px;'
        f'border-radius:50%;border:2px solid {ring};background:{ring}26;'
        f'color:{ring};align-items:center;justify-content:center;'
        f'font-weight:800;font-size:{size * 0.34:.0f}px;vertical-align:middle">'
        f'{initials}</span>'
    )
