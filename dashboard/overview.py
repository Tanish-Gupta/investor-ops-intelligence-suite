"""Home ("Today's briefing") and System health pages."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import streamlit as st

from config.settings import get_settings

from . import health
from .shell import APPROVALS, ASK, BOOK, EVALS, HEALTH, NOTES, PULSE
from .ui_kit import callout, empty_state, esc, go_button, kv, page_header, pill, section

HEALTH_LABEL = {True: ("Healthy", "ok"), None: ("Degraded", "warn"), False: ("Down", "bad")}


@dataclass(frozen=True)
class Step:
    key: str
    title: str
    body: str
    page: str
    cta: str
    status: str  # "done" | "todo" | "waiting" | "anytime"
    note: str = ""


def _steps(s: dict, ev: dict | None, has_lines: bool) -> list[Step]:
    booked, pending = s["bookings"] > 0, s["pending_approvals"]
    return [
        Step("pulse", "Brief the team with this week's review pulse",
             "Classify app reviews, rank themes and write a ≤ 250-word pulse. Its top theme "
             "briefs the voice agent.", PULSE, "Open pulse",
             "done" if s["pulse_id"] else "todo"),
        Step("ask", "Answer an investor question",
             "Six cited bullets that combine factsheet facts with the fee explainer.", ASK,
             "Ask a question", "anytime"),
        Step("book", "Book an advisor call",
             "The theme-aware agent greets the caller, books a slot and issues a booking code.",
             BOOK, "Start a call", "done" if booked else "todo"),
        Step("approve", "Review and approve the follow-ups",
             "Calendar hold, notes line and advisor email (with Market Context) wait for you.",
             APPROVALS, "Review approvals",
             "waiting" if pending else ("done" if booked else "todo"),
             f"{pending} waiting" if pending else ""),
        Step("notes", "Check the pre-booking notes",
             "Each approved booking line carries its booking code and Weekly Pulse id.", NOTES,
             "Open notes", "done" if has_lines else "todo"),
        Step("evals", "Prove it works",
             "Run the RAG, safety, UX and integration evaluations.", EVALS, "Open evaluations",
             "done" if ev and ev.get("all_passed") else "todo"),
    ]  # fmt: skip


STATUS_PILL = {
    "done": ("Done", "ok"), "todo": ("To do", "neutral"), "waiting": ("Needs review", "warn"),
    "anytime": ("Anytime", "info"),
}  # fmt: skip


def _render_steps(steps: list[Step]) -> None:
    first = next((st_.key for st_ in steps if st_.status in ("todo", "waiting")), None)
    for i, step in enumerate(steps, 1):
        with st.container(border=True):
            left, right = st.columns([5, 1.6], vertical_alignment="center")
            label, tone = STATUS_PILL[step.status]
            note = f" · {esc(step.note)}" if step.note else ""
            left.markdown(
                f"**{i}. {esc(step.title)}** &nbsp;{pill(label, tone)}{note}",
                unsafe_allow_html=True,
            )
            left.caption(step.body)
            with right:
                go_button(step.cta, step.page, key=f"home_go_{step.key}",
                          primary=step.key == first)  # fmt: skip


def _pulse_panel() -> None:
    from pillar_b_voice.greeting import build_greeting
    from pillar_m2_pulse.pulse import get_latest_pulse

    p = get_latest_pulse()
    section("Customer pulse")
    if p is None:
        empty_state(
            "No pulse this week",
            "Generate the Weekly Pulse to learn what customers are raising. The voice agent "
            "uses a generic greeting until then.",
            cta="Generate pulse", page=PULSE, key="home_empty_pulse",
        )  # fmt: skip
        return
    with st.container(border=True):
        st.markdown(
            f"{pill(p.pulse_id, 'neutral')} {pill(f'{p.review_count} reviews', 'neutral')}",
            unsafe_allow_html=True,
        )
        st.markdown(f"**Top theme:** {esc(p.top_theme or 'none')}", unsafe_allow_html=True)
        callout("Market context · shared with advisors", p.market_context, "warn")
        callout("Voice agent will open with", build_greeting(p).text, "info")


def _health_panel() -> None:
    section("System health")
    checks = health.checks()
    bad = [c for c in checks if c.ok is False]
    degraded = [c for c in checks if c.ok is None]
    with st.container(border=True):
        if bad:
            head = pill(f"{len(bad)} down", "bad")
        elif degraded:
            head = pill(f"{len(degraded)} degraded", "warn")
        else:
            head = pill("All systems normal", "ok")
        rows = "".join(
            f"<div class='io-source'>{pill(*HEALTH_LABEL[c.ok])}<span>{esc(c.name)}</span></div>"
            for c in checks
        )
        st.markdown(head + rows, unsafe_allow_html=True)
        go_button("View details", HEALTH, key="home_go_health")


def render() -> None:
    from core import notes

    today = datetime.now(get_settings().tz)
    page_header(
        f"Operations · {today:%A, %d %B}",
        "Today's briefing",
        "What customers are telling us, what's waiting for your review, and whether the suite "
        "is healthy.",
    )
    s = health.summary()
    ev = health.last_eval()
    if s["failed_actions"] or s["needs_attention"]:
        callout(
            "Needs attention",
            f"{s['failed_actions']} failed action(s) and {s['needs_attention']} booking(s) need "
            "attention.",
            "bad",
        )
        go_button("Open approvals", APPROVALS, key="home_go_attention", primary=True)

    c = st.columns(4)
    c[0].metric("Top theme", s["top_theme"] or "—", help=s["pulse_id"] or "No pulse yet",
                border=True)  # fmt: skip
    c[1].metric("Pending approvals", s["pending_approvals"], border=True)
    c[2].metric("Bookings", s["bookings"], border=True)
    c[3].metric(
        "Last eval",
        f"{ev['passed']}/{ev['total']}" if ev else "—",
        help=ev.get("generated_at") if ev else "Run the evaluations",
        border=True,
    )

    left, right = st.columns([1.45, 1], gap="large")
    with left:
        section("Next steps")
        _render_steps(_steps(s, ev, bool(notes.booking_lines())))
    with right:
        _pulse_panel()
        _health_panel()


def render_health() -> None:
    s = get_settings()
    page_header(
        "Quality",
        "System health",
        "Live readiness checks for every moving part. Computing them never calls an LLM.",
    )
    for chk in health.checks():
        label, tone = HEALTH_LABEL[chk.ok]
        with st.container(border=True):
            a, b = st.columns([5, 1], vertical_alignment="center")
            a.markdown(f"**{esc(chk.name)}**", unsafe_allow_html=True)
            a.caption(chk.detail)
            b.markdown(pill(label, tone), unsafe_allow_html=True)

    section("Configuration")
    on = {True: "on", False: "off"}
    with st.container(border=True):
        st.markdown(
            kv([
                ("Tool backends", f"{s.adapter_mode} (FastMCP server)"),
                ("Timezone", s.timezone),
                ("LLM keys", ", ".join(n for n, k in (("Gemini", s.gemini_api_key),
                                                       ("Groq", s.groq_api_key)) if k) or "none"),
                ("Unified Search LLM", on[s.rag_llm_enabled]),
                ("Pulse LLM", on[s.pulse_llm_enabled]),
                ("Voice NLU LLM", on[s.voice_llm_enabled]),
                ("Safety guard LLM", on[s.guard_llm_enabled]),
                ("Mic input / spoken replies",
                 f"{on[s.voice_stt_enabled]} / {on[s.voice_tts_enabled]}"),
            ]),
            unsafe_allow_html=True,
        )  # fmt: skip
        st.caption(
            "LLM features only run when a key is present; every one falls back to rules and "
            "templates, so the suite works offline."
        )
