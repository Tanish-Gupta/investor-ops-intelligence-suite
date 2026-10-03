"""Review pulse page (Admin portal, M2): app-store reviews in, the Weekly Pulse out. The pulse's
top theme briefs the voice agent and its Market Context goes into every advisor email."""

from __future__ import annotations

import streamlit as st

from config.settings import get_settings
from dashboard.shell import BOOK
from dashboard.ui_kit import (
    bars,
    card,
    card_head,
    empty_state,
    esc,
    go_button,
    html_block,
    masthead,
    tag,
)

from .pulse import PulseResult, get_latest_pulse, run_pulse
from .reviews import ReviewInputError

MAX_UPLOAD_MB = 10
FUNNEL = [
    ("input", "Rows in the file"),
    ("valid", "Readable reviews"),
    ("in_window", "Inside the week's window"),
    ("min_words", "Long enough to classify"),
    ("deduped", "Unique reviews analysed"),
]


def _range(p: PulseResult) -> str:
    if p.week_start and p.week_end:
        return f"{p.week_start:%d %b} to {p.week_end:%d %b %Y}"
    return "latest window"


def _funnel(p: PulseResult) -> None:
    prep = p.prep or {}
    with card("funnel"):
        card_head("How the reviews were read", "Personal data masked before analysis",
                  icon_name="notes", tone="sage")  # fmt: skip
        if not prep.get("input"):
            html_block(f'<p class="io-foot-cap">{p.review_count:,} reviews analysed. Process a '
                       "file to see each cleaning step.</p>")  # fmt: skip
            return
        total = prep["input"]
        rows = [(label, prep.get(k, 0) / total, f"{prep.get(k, 0):,}") for k, label in FUNNEL
                if k in prep]  # fmt: skip
        html_block(bars(rows, top=rows[-1][0], tone="sage"))
        c = p.classifier or {}
        kinds = (("llm", "by LLM"), ("cached", "from cache"), ("keyword", "by keyword rules"))
        by = ", ".join(f"{c[k]:,} {lbl}" for k, lbl in kinds if c.get(k))
        if by:
            html_block(f'<p class="io-foot-cap">Themes assigned: {esc(by)}.</p>')


def _process(up, week, use_llm: bool) -> PulseResult | None:  # noqa: ANN001
    if up is not None and up.size > MAX_UPLOAD_MB * 1024 * 1024:
        st.error(f"That file is over {MAX_UPLOAD_MB} MB. Upload a smaller export.")
        return None
    src = up.name if up is not None else "the sample export"
    with st.status(f"Processing {src}…", expanded=True) as box:
        st.write("Cleaning rows and masking personal data.")
        st.write("Sorting every review into a theme.")
        st.write("Ranking themes and writing the one-page pulse.")
        try:
            p = run_pulse(up, week=week, use_llm=use_llm)
        except ReviewInputError as exc:
            box.update(label="Couldn't read those reviews", state="error")
            st.error(str(exc))
            return None
        box.update(label=f"Pulse {p.pulse_id} ready. Top theme: {p.top_theme or 'none'}.",
                   state="complete", expanded=False)  # fmt: skip
    from pillar_b_voice.ui import _new_call

    _new_call()  # the next call opens with the new briefing
    st.session_state["pulse_id"] = p.pulse_id
    return p


def _intake() -> PulseResult | None:
    s = get_settings()
    with card("intake"):
        card_head("Reviews in", "App-store export: date, rating and text columns",
                  icon_name="upload")  # fmt: skip
        up = st.file_uploader("Reviews CSV", type="csv", key="pulse_upload",
                              label_visibility="collapsed")  # fmt: skip
        with st.container(horizontal=True, vertical_alignment="center"):
            go = st.button("Process reviews", type="primary", key="pulse_run",
                           icon=":material/play_arrow:")  # fmt: skip
            with st.popover("Options", icon=":material/tune:"):
                week = st.date_input(
                    "Window ends on",
                    value=None,
                    key="pulse_week",
                    help="Leave empty to use the latest week in the file.",
                )
                use_llm = st.toggle(
                    "Classify with the LLM",
                    value=s.pulse_llm_enabled,
                    key="pulse_llm",
                    help="Falls back to keyword rules if no API key is set.",
                )
        html_block('<p class="io-foot-cap">No file? The bundled sample export is used.</p>')
    return _process(up, week, use_llm) if go else None


def _doc(p: PulseResult) -> None:
    s = get_settings()
    with card("doc"):
        meta = tag(f"{p.word_count} words · {p.action_idea_count} action ideas", "muted")
        card_head("Weekly pulse", f"{p.pulse_id} · {_range(p)}", icon_name="pulse", end=meta)
        st.markdown(p.pulse_md)
        html_block(f'<p class="io-foot-cap">One page, at most {s.pulse_max_words} words. Quotes '
                   "are attributed as [REDACTED].</p>")  # fmt: skip
        st.download_button("Download pulse", p.pulse_md, file_name=f"pulse_{p.pulse_id}.md",
                           mime="text/markdown", icon=":material/download:",
                           key="pulse_download")  # fmt: skip


def _themes(p: PulseResult) -> None:
    rows = [t for t in p.themes if t.get("theme") != "Other" and t.get("count")]
    with card("themes"):
        card_head("Themes this week", f"{p.review_count:,} reviews", icon_name="search")
        if not rows:
            html_block('<p class="io-foot-cap">No theme stood out this week.</p>')
            return
        peak = max(t["count"] for t in rows)
        data = [(t["theme"], t["count"] / peak, f"{t['count']:,} · {t.get('share', 0):.0%}")
                for t in rows[:7]]  # fmt: skip
        html_block(bars(data, top=p.top_theme))


def _briefs(p: PulseResult) -> None:
    from pillar_b_voice.greeting import build_greeting

    with card("agent", tone="sage"):
        card_head("Briefs the voice agent", "How the next call opens", icon_name="voice",
                  tone="sage")  # fmt: skip
        html_block(f'<div class="io-quote serif">{esc(build_greeting(p).text)}</div>')
        go_button("Try it in a call", BOOK, key="pulse_to_book", icon=":material/call:")
    with card("mc", tone="iris"):
        card_head("Market Context", "Added to every advisor email", icon_name="mail", tone="iris")
        html_block(f'<div class="io-quote">{esc(p.market_context)}</div>')


def render_pulse(p: PulseResult) -> None:
    st.session_state["pulse_id"] = p.pulse_id
    left, right = st.columns([1.6, 1], gap="large")
    with left:
        _doc(p)
    with right:
        _briefs(p)
        _themes(p)


def render() -> None:
    masthead(
        "Review pulse",
        "Turn this week's app-store reviews into a one-page pulse. Its top theme briefs the voice "
        "agent, and its Market Context goes into every advisor email.",
        "Admin portal",
    )
    top_l, top_r = st.columns([1.6, 1], gap="large")
    with top_l:
        fresh = _intake()
    p = fresh or get_latest_pulse()
    with top_r:
        if p is not None:
            _funnel(p)
    html_block('<div style="height:.6rem"></div>')
    if p is None:
        empty_state("No pulse yet", "Process the sample export or upload your own CSV above.")
        return
    render_pulse(p)
