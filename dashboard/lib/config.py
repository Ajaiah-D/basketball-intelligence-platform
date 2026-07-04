"""Runtime settings resolved from Streamlit secrets (cloud) first, then
environment / .env (local). Never hardcode secrets in the repo."""

from __future__ import annotations

import os

import streamlit as st
from dotenv import load_dotenv

load_dotenv()


def setting(name: str, default: str | None = None) -> str | None:
    """st.secrets wins (Streamlit Cloud), then env vars / .env, then default."""
    try:
        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:  # no secrets.toml present locally
        pass
    return os.getenv(name, default)


def dev_lab_enabled() -> bool:
    """Hide the Dev Lab entirely on public deploys with DEV_LAB_ENABLED=false."""
    return str(setting("DEV_LAB_ENABLED", "true")).lower() in ("1", "true", "yes")


def dev_password() -> str | None:
    return setting("DEV_PASSWORD")


def warehouse_url() -> str | None:
    """Optional URL to download the DuckDB warehouse from on first boot
    (e.g. a GitHub Release asset) - used by cloud deploys where the
    warehouse file is not in the repo."""
    return setting("WAREHOUSE_URL")
