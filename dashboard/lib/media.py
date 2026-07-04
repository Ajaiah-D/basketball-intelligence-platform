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
