"""Navigation registry and per-page error boundary for the multipage app."""

from __future__ import annotations

import importlib
import logging

import streamlit as st

HOME = "views/home.py"
ASK = "views/ask.py"
BOOK = "views/book.py"
PULSE = "views/pulse.py"
APPROVALS = "views/approvals.py"
# Retired ops pages (not in navigation; evals run from the CLI). Kept so old modules import.
NOTES = "views/notes.py"
EVALS = "views/evals.py"
HEALTH = "views/health.py"

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
