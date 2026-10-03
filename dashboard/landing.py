"""Home: the landing page. One serif headline, the two portals, the three pillars as raised cards
carrying live numbers, and the demo flow that connects them."""

from __future__ import annotations

import logging

import streamlit as st

from dashboard.shell import APPROVALS, ASK, BOOK, PULSE
from dashboard.ui_kit import card, esc, go_button, html_block, icon

log = logging.getLogger("app")

FLOW = [
    ("Upload reviews", "An app-store export becomes this week's review pulse."),
    ("Brief the agent", "The pulse's top theme shapes how the voice agent opens a call."),
    ("Book a call", "The caller picks a slot and gets a booking code."),
    ("Approve follow-ups", "Hold and advisor email with Market Context; the code lands in notes."),
]


def _live() -> dict:
    """Numbers for the pillar cards. Cosmetic: never let them break the landing page."""
    out = {"funds": 5, "sources": 0, "theme": None, "pending": 0}
    try:
        from pillar_a_kb.corpus import load_sources, schemes

        out["funds"], out["sources"] = len(schemes()), len(load_sources())
    except Exception:  # noqa: BLE001
        log.exception("landing_sources_failed")
    try:
        from dashboard.health import summary

        s = summary()
        out["theme"], out["pending"] = s["top_theme"], int(s["pending_approvals"])
    except Exception:  # noqa: BLE001
        log.exception("landing_summary_failed")
    return out


def _pillar(name: str, tone: str, glyph: str, title: str, body: str, live: str, page: str,
            link: str) -> None:  # fmt: skip
    with card(name, tone="link"):
        html_block(
            f'<div class="io-pillar">{icon(glyph, tone)}<h3>{esc(title)}</h3><p>{esc(body)}</p>'
            f'<div class="io-live">{live}</div></div>'
        )
        st.page_link(page, label=link, icon=":material/arrow_forward:")


def render() -> None:
    html_block(
        '<section class="io-hero"><h1 class="io-title">Investor ops and intelligence, in one '
        "place.</h1><p>Answer fund and fee questions with sources, let this week's app reviews "
        "brief the voice agent, and sign off every advisor follow-up before it goes out.</p>"
        "</section>"
    )
    with st.container(horizontal=True, horizontal_alignment="center", key="io-cta"):
        go_button("Customer portal", ASK, key="home_customer", primary=True,
                  icon=":material/person:")  # fmt: skip
        go_button("Admin portal", PULSE, key="home_admin", icon=":material/admin_panel_settings:")
    html_block('<div style="height:1.6rem"></div>')

    n = _live()
    theme = n["theme"] or "No pulse yet"
    pending = n["pending"]
    a, b, c = st.columns(3, gap="medium")
    with a:
        _pillar(
            "a", "brand", "search", "Smart-Sync answers",
            "Ask about a fund and a fee in one question. Facts come from the scheme factsheet, "
            "the why from the fee explainer: six points, each cited.",
            f"<b>{n['funds']} funds</b><span>{n['sources']} official sources</span>",
            ASK, "Ask a question",
        )  # fmt: skip
    with b:
        _pillar(
            "b", "sage", "voice", "Theme-aware voice agent",
            "The agent reads this week's review pulse and opens the call with what customers "
            "are raising, then books a tentative advisor slot.",
            f"<b>{esc(theme)}</b><span>top theme in this week's reviews</span>",
            BOOK, "Book a call",
        )  # fmt: skip
    with c:
        _pillar(
            "c", "iris", "approve", "Approval center",
            "Every call ends in a calendar hold and an advisor email with Market Context from "
            "the pulse. Nothing is filed until someone approves it.",
            f"<b>{pending}</b><span>follow-up{'s' if pending != 1 else ''} waiting for "
            "approval</span>",
            APPROVALS, "Open approvals",
        )  # fmt: skip

    steps = "".join(
        f'<li><span class="n">{i}</span><span><b>{esc(t)}</b><span class="d">{esc(d)}</span>'
        "</span></li>"
        for i, (t, d) in enumerate(FLOW, start=1)
    )
    html_block(f'<ol class="io-flow" aria-label="How the suite connects">{steps}</ol>')
