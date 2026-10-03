"""Ask page (Pillar A, Unified Search): one question in, a numbered reply out. Scheme facts come
from the M1 factsheets and fee logic from the M2 fee explainer; six points, each footnoted to its
source. Coverage questions ("which funds / sources do you have?") are answered from the registry."""

from __future__ import annotations

import uuid

import streamlit as st

from config.settings import get_settings
from dashboard.shell import BOOK
from dashboard.ui_kit import (
    card,
    card_head,
    empty_state,
    esc,
    go_button,
    heading,
    html_block,
    masthead,
    note,
    tag,
)
from dashboard.ui_kit import today as _today

EXAMPLES = [
    "What is the exit load for the ELSS fund and why was I charged it?",
    "I redeemed my Flexi Cap units 8 months after buying. What exit load applies and how is it "
    "calculated?",
    "I withdrew from the liquid fund 3 days after investing — why is the amount slightly lower "
    "than expected?",
    "What is the expense ratio of the Index fund and does it get deducted from my account "
    "separately?",
    "My ₹10,000 SIP in the Large Cap fund showed ₹9,999.50 invested. What is the minimum SIP "
    "and why the difference?",
]
MAX_QUERY_CHARS = 600
_STATUS = {
    "ANSWERED": ("Answered", "sage"),
    "PARTIAL": ("Partly answered", "amber"),
    "NOT_FOUND": ("Not in the sources", "muted"),
    "REFUSED": ("Declined", "red"),
    "CLARIFY": ("Needs a detail", "ink"),
    "UNAVAILABLE": ("Sources unavailable", "amber"),
}


@st.cache_resource(show_spinner="Loading search models (first time only)…")
def _warm_models() -> bool:
    """Load the embedder and reranker once per server process. False if they are missing."""
    from pillar_a_kb import models

    if get_settings().kb_lite:  # keyword search by design; nothing to warm
        return True
    try:
        models.embed_query("exit load")
        models.rerank("exit load", ["Exit load is a charge on early redemption."])
    except models.ModelUnavailable:
        return False
    return True


def _manifest() -> dict | None:
    from pillar_a_kb.ingest import read_manifest

    return read_manifest()


@st.cache_resource(show_spinner="Preparing the fund library…")
def _lite_index() -> bool:
    """Build the keyword-only index once per server process (lite runtime)."""
    from pillar_a_kb.ingest import ingest
    from pillar_a_kb.retriever import get_retriever

    ingest(rebuild=True, use_docling=False)
    get_retriever(refresh=True)
    return True


def _sync_index(rebuild: bool = False) -> None:
    from pillar_a_kb.ingest import ingest
    from pillar_a_kb.retriever import get_retriever

    with st.spinner("Syncing sources into the knowledge base…"):
        report = ingest(rebuild=rebuild)
    get_retriever(refresh=True)
    st.session_state["kb_sync_msg"] = (
        f"Synced: {len(report['updated_documents'])} document(s) updated, "
        f"{report['total_chunks']} chunks in {report['seconds']} s."
    )


def _md(text: str) -> str:
    """Escape characters Streamlit markdown would otherwise interpret."""
    return text.replace("$", "\\$").replace("*", "\\*").replace("_", "\\_")


SHORT = [
    "ELSS exit load",
    "Flexi Cap after 8 months",
    "Liquid fund after 3 days",
    "Index fund expense ratio",
    "Large Cap minimum SIP",
]


def _source_kind(source_type: str) -> str:
    if source_type == "M1_FACTSHEET":
        return "Scheme factsheet"
    if source_type.startswith("M2"):
        return "Fee explainer"
    return "Regulator / AMC"


def _paras_html(ans) -> str:  # noqa: ANN001
    url_by_n = {c.n: c.url for c in ans.citations}
    items = []
    for bullet, nums in zip(ans.bullets, ans.bullet_citations, strict=False):
        cites = "".join(
            f'<a href="{esc(url_by_n[n])}" target="_blank" rel="noopener" '
            f'aria-label="Source {n}">{n}</a>'
            for n in nums if n in url_by_n
        )  # fmt: skip
        fn = f'<sup class="io-fn">{cites}</sup>' if cites else ""
        items.append(f"<li>{esc(bullet)}{fn}</li>")
    return f'<ol class="io-paras">{"".join(items)}</ol>'


def _notes_html(ans) -> str:  # noqa: ANN001
    rows = "".join(
        f'<li><sup>{c.n}</sup><span><a href="{esc(c.url)}" target="_blank" rel="noopener">'
        f"{esc(c.title)}</a>. {esc(_source_kind(c.source_type))}, retrieved "
        f"{esc(c.fetched_on)}.</span></li>"
        for c in ans.citations
    )
    return f'<div class="io-notes" aria-label="Sources"><ol>{rows}</ol></div>'


class Library:
    """A coverage question ("which funds / sources do you have?"), answered from the registry."""

    status = "LIBRARY"


def _library_data() -> dict:
    from pillar_a_kb.corpus import load_sources, schemes

    srcs = load_sources()
    return {
        "funds": [(s.canonical, s.category) for s in schemes()],
        "sources": srcs,
        "counts": {
            k: sum(1 for s in srcs if s.source_type == k)
            for k in ("M1_FACTSHEET", "M2_FEE_EXPLAINER", "M1_REGULATOR")
        },
    }


def _sources_html(srcs) -> str:  # noqa: ANN001
    rows = "".join(
        f'<li><sup>{i}</sup><span><a href="{esc(s.url)}" target="_blank" rel="noopener">'
        f"{esc(s.title)}</a>. {esc(_source_kind(s.source_type))}, retrieved "
        f"{esc(s.fetched_on)}.</span></li>"
        for i, s in enumerate(srcs, start=1)
    )
    return f'<div class="io-notes" aria-label="Sources"><ol>{rows}</ol></div>'


def render_library_answer(question: str | None = None, ref: str = "") -> None:
    from pillar_a_kb.catalog import catalog_reply

    reply = catalog_reply()
    head = [f'<span class="ref">Ref. {esc(ref)}</span>'] if ref else []
    head += [f"<span>{_today()}</span>", tag("From the library", "brand")]
    items = "".join(f"<li>{esc(b)}</li>" for b in reply.bullets)
    parts = [f'<div class="io-circ-head">{"".join(head)}</div>']
    if question:
        parts.append(f'<p class="io-subject">{esc(question)}</p>')
    parts.append(f'<ol class="io-paras">{items}</ol>')
    html_block("".join(parts))
    srcs = _library_data()["sources"]
    with st.expander(f"All {len(srcs)} sources"):
        html_block(_sources_html(srcs))


def library_card() -> None:
    """What Unified Search can answer: the 30 funds (two AMCs) and the kinds of source."""
    try:
        data = _library_data()
    except Exception:  # noqa: BLE001
        return
    c = data["counts"]
    with card("library", tone="brand"):
        card_head("What I can answer", f"{len(data['sources'])} official sources",
                  icon_name="book")  # fmt: skip
        groups: dict[str, list[str]] = {}
        for n, cat in data["funds"]:
            amc = "Bajaj Finserv MF" if n.startswith("Bajaj") else "Edelweiss MF"
            short = n.removeprefix("Bajaj Finserv ").removeprefix("Edelweiss ")
            groups.setdefault(amc, []).append(f"<li>{esc(short)}<span>{esc(cat)}</span></li>")
        lists = "".join(
            f'<p class="io-lib-amc">{esc(amc)} <span>{len(rows)}</span></p>'
            f'<ul class="io-lib" aria-label="{esc(amc)} funds">{"".join(rows)}</ul>'
            for amc, rows in groups.items()
        )
        html_block(
            f'<div class="io-lib-scroll" tabindex="0" role="region" '
            f'aria-label="{len(data["funds"])} funds covered">{lists}</div>'
        )
        fs, fx, rg = c["M1_FACTSHEET"], c["M2_FEE_EXPLAINER"], c["M1_REGULATOR"]
        html_block(
            f'<div class="io-chips">{tag(f"{fs} fund documents", "brand")}'
            f"{tag(f'{fx} fee explainers', 'sage')}{tag(f'{rg} SEBI / AMFI pages', 'iris')}</div>"
            '<p class="io-foot-cap">Exit load, expense ratio, lock-in, minimum SIP, benchmark and '
            "riskometer per fund, plus why each fee is charged.</p>"
        )
        with st.popover("See every source", icon=":material/menu_book:", width="stretch"):
            html_block(_sources_html(data["sources"]))


def render_answer(ans, question: str | None = None, ref: str = "") -> None:  # noqa: ANN001
    if isinstance(ans, Library):
        render_library_answer(question, ref)
        return
    label, tone = _STATUS.get(ans.status, (ans.status.title(), "muted"))
    head = [f'<span class="ref">Ref. {esc(ref)}</span>'] if ref else []
    head.append(f"<span>{_today()}</span>")
    head.append(tag(label, tone))
    if ans.scheme:
        head.append(tag(ans.scheme, "ink"))
    parts = [f'<article class="io-circ"><div class="io-circ-head">{"".join(head)}</div>']
    if question:
        parts.append(f'<p class="io-subject">{esc(question)}</p>')
    if ans.status in ("ANSWERED", "PARTIAL"):
        parts.append(_paras_html(ans))
    else:
        parts.append(f'<p class="io-body">{esc(ans.message or "")}</p>')
        if ans.links:
            links = "".join(
                f'<li><a href="{esc(u)}" target="_blank" rel="noopener">{esc(u)}</a></li>'
                for u in ans.links
            )
            parts.append(f'<ul class="io-body">{links}</ul>')
    if ans.citations:
        parts.append(_notes_html(ans))
    if ans.last_updated:
        parts.append(f'<p class="io-foot-cap">Facts as of {esc(ans.last_updated)}.</p>')
    parts.append("</article>")
    html_block("".join(parts))
    for text in ans.notices:
        note(text, "amber")


def render() -> None:
    masthead(
        "Ask about your mutual fund",
        "Exit load, expense ratio, lock-in, minimum SIP, and why a fee was charged. Every reply "
        "is six numbered points, each with its source.",
        "Customer portal",
    )
    manifest = _manifest()
    st.session_state.setdefault("session_id", uuid.uuid4().hex[:12])
    history: list[tuple[str, object, str]] = st.session_state.setdefault("kb_history", [])

    if manifest is None and get_settings().kb_lite:
        _lite_index()  # fresh cloud container: the keyword index builds in seconds
        manifest = _manifest()
    if manifest is None:
        empty_state(
            "The fund library isn't loaded yet",
            "Load the scheme factsheets and fee explainers once. It takes about a minute.",
        )
        if st.button("Load the library", type="primary", key="kb_build"):
            _sync_index(rebuild=True)
            st.rerun()
        return
    if not _warm_models():
        note(
            "Search is running on the verified fact sheet only, so some questions may come back "
            "unanswered. Ask your administrator to install the search models.",
            "amber",
        )

    main, side = st.columns([1.85, 1], gap="large")
    with main:
        with card("ask"):
            card_head("Your question", "A fund fact and a fee, in one go", icon_name="search")
            with st.form("kb_form", clear_on_submit=True, border=False):
                typed = st.text_input(
                    "Your question",
                    placeholder="e.g. Why was I charged an exit load on my Flexi Cap redemption?",
                    max_chars=MAX_QUERY_CHARS,
                    label_visibility="collapsed",
                )
                submitted = st.form_submit_button("Ask", type="primary", icon=":material/search:")
            html_block('<p class="io-foot-cap">Common questions</p>')
            picked = None
            with st.container(horizontal=True):
                for i, (short, q) in enumerate(zip(SHORT, EXAMPLES, strict=True)):
                    if st.button(short, key=f"kb_ex_{i}", help=q):
                        picked = q
        query = picked or (typed.strip() if submitted else "")

        if query:
            from pillar_a_kb.catalog import is_catalog_question

            if is_catalog_question(query):
                ans = Library()
            else:
                from pillar_a_kb.service import answer

                with st.spinner("Checking the factsheets and fee explainers…"):
                    ans = answer(query, session_id=st.session_state["session_id"])
            n = st.session_state["kb_seq"] = st.session_state.get("kb_seq", 0) + 1
            history.insert(0, (query, ans, f"Q-{n:04d}"))
            del history[10:]

        if history:
            q, ans, ref = history[0]
            with card("answer"):
                render_answer(ans, q, ref)
            a, b = st.columns([3, 1.3], vertical_alignment="center")
            a.markdown("Still unsure? Talk it through with an advisor. You won't be asked for "
                       "personal details on the call.")  # fmt: skip
            with b:
                go_button("Book an advisor call", BOOK, key="kb_to_book", icon=":material/call:")
            if len(history) > 1:
                heading("Earlier questions")
                for q, ans, ref in history[1:]:
                    with st.expander(f"{ref}  {q}"):
                        render_answer(ans, ref=ref)
            if st.button("Clear earlier questions", key="kb_clear", type="tertiary"):
                history.clear()
                st.rerun()
    with side:
        library_card()
