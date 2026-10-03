"""Investor Ops & Intelligence Suite: the single Streamlit entry point.

Home (landing) plus two portals:
  Customer portal
    Ask           Unified Search: M1 factsheet facts + M2 fee logic in six cited points.
    Book a call   Theme-aware voice agent, briefed by the Weekly Pulse (M2).
  Admin portal
    Review pulse  App-store reviews CSV -> Weekly Pulse (top themes, quotes, 3 action ideas,
                  Market Context); the pulse briefs the voice agent.
    Approvals     HITL sign-off of the calendar hold + advisor email draft (with Market Context);
                  approved bookings land in the pre-booking notes register with their booking code.

Run with: `uv run streamlit run app.py`. Evals run from the CLI: `uv run python -m evals.run_evals`.
"""

from __future__ import annotations

import logging
from pathlib import Path

import streamlit as st

from config.settings import get_settings
from core.logging import configure_logging
from dashboard import shell
from dashboard.ui_kit import footer, inject_css

configure_logging()
ASSETS = Path(__file__).resolve().parent / "assets"
log = logging.getLogger("app")


def _pending() -> int:
    try:
        from dashboard.health import summary

        return int(summary()["pending_approvals"])
    except Exception:  # noqa: BLE001 - the count is cosmetic; never block navigation
        log.exception("pending_count_failed")
        return 0


def ensure_pulse() -> None:
    """The voice agent is theme-aware only if a Weekly Pulse exists, so build one from the bundled
    reviews CSV on a session's first visit. Never blocks the app if it fails."""
    if st.session_state.get("pulse_checked") or not get_settings().pulse_autobuild:
        return
    st.session_state["pulse_checked"] = True
    try:
        from pillar_m2_pulse.pulse import get_latest_pulse, run_pulse

        if get_latest_pulse() is None:
            with st.spinner("Reading this week's app reviews…"):
                run_pulse(None)
    except Exception:  # noqa: BLE001 - the greeting falls back to generic
        log.exception("pulse_autobuild_failed")


def navigation() -> st.navigation:
    n = _pending()
    return st.navigation(
        {
            "": [st.Page(shell.HOME, title="Home", icon=":material/home:", default=True)],
            "Customer portal": [
                st.Page(shell.ASK, title="Ask", icon=":material/search:", url_path="ask"),
                st.Page(shell.BOOK, title="Book a call", icon=":material/call:", url_path="book"),
            ],
            "Admin portal": [
                st.Page(shell.PULSE, title="Review pulse", icon=":material/monitoring:",
                        url_path="pulse"),
                st.Page(shell.APPROVALS, title=f"Approvals ({n})" if n else "Approvals",
                        icon=":material/approval:", url_path="approvals"),
            ],
        },
        position="top",
    )  # fmt: skip


def main() -> None:
    st.set_page_config(
        page_title="Investor Ops & Intelligence Suite",
        page_icon=str(ASSETS / "icon.svg"),
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    st.logo(str(ASSETS / "logo.svg"), size="large", icon_image=str(ASSETS / "icon.svg"))
    inject_css()
    ensure_pulse()
    pg = navigation()
    pg.run()
    footer(f"{shell.DISCLAIMER} Caller names are always shown as [REDACTED].")


main()
