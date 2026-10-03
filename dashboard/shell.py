"""Navigation registry and per-page error boundary for the multipage app."""

from __future__ import annotations

import importlib
import logging
from pathlib import Path

import streamlit as st

# Absolute paths: Streamlit resolves page files against the main script's folder, and the
# Streamlit Cloud entry point (cloud/streamlit_app.py) lives in a subfolder.
_VIEWS = Path(__file__).resolve().parent.parent / "views"
HOME = str(_VIEWS / "home.py")
ASK = str(_VIEWS / "ask.py")
BOOK = str(_VIEWS / "book.py")
PULSE = str(_VIEWS / "pulse.py")
APPROVALS = str(_VIEWS / "approvals.py")
# Retired ops pages (not in navigation; evals run from the CLI). Kept so old modules import.
NOTES = str(_VIEWS / "notes.py")
EVALS = str(_VIEWS / "evals.py")
HEALTH = str(_VIEWS / "health.py")

DISCLAIMER = "Facts only. No investment advice."


def run_page(name: str, module: str, fn: str = "render") -> None:
    """Graceful degradation: a failing page shows a banner; navigation and other pages still work.

    The renderer is imported lazily so an import-time failure is contained too."""
    try:
        getattr(importlib.import_module(module), fn)()
    except Exception as e:  # noqa: BLE001 - surface any page failure as a banner
        logging.getLogger("app").exception("page_failed", extra={"page": name})
        st.error(
            f"{name} is temporarily unavailable ({type(e).__name__}). "
            "Other pages still work — pick one from the top bar."
        )
