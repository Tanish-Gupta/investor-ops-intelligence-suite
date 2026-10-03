"""Approvals page (Pillar C, HITL): every follow-up a call produces (calendar hold, advisor email
draft with the Weekly Pulse's Market Context, notes line) is an annexure that waits for a stamp.
Approved bookings are entered in the pre-booking notes register with their booking code."""

from __future__ import annotations

from datetime import datetime

import streamlit as st

from core import notes
from dashboard.shell import BOOK
from dashboard.ui_kit import (
    card,
    card_head,
    empty_state,
    esc,
    heading,
    html_block,
    icon,
    kv,
    masthead,
    note,
    stamp,
    tag,
)

from . import actions
from .actions import ActionView, ApprovalError
from .plan import CREATE_HOLD, DELETE_HOLD, DOCS_APPEND, GMAIL_DRAFT

TOOL_LABEL = {
    CREATE_HOLD: "Calendar hold", DELETE_HOLD: "Release calendar hold",
    DOCS_APPEND: "Notes line", GMAIL_DRAFT: "Advisor email draft",
}  # fmt: skip
TOOL_SUB = {
    CREATE_HOLD: "advisor's calendar", DELETE_HOLD: "advisor's calendar",
    DOCS_APPEND: "pre-booking notes", GMAIL_DRAFT: "drafted, never sent",
}  # fmt: skip
TOOL_ICON = {CREATE_HOLD: "calendar", DELETE_HOLD: "calendar", DOCS_APPEND: "notes",
             GMAIL_DRAFT: "mail"}  # fmt: skip
BOOKING_STATUS = {"CONFIRMED": ("Confirmed", "sage"), "TENTATIVE": ("Tentative", "amber"),
                  "NEEDS_ATTENTION": ("Needs attention", "red")}  # fmt: skip
DEFAULT_REVIEWER = "ops-reviewer"
REGISTER_COLS = ("Date", "Topic", "Slot", "Booking code", "Status", "Review pulse")


def _when(start: str | None, end: str | None) -> str:
    try:
        a, b = datetime.fromisoformat(str(start)), datetime.fromisoformat(str(end))
    except ValueError:
        return f"{start} to {end}"
    return f"{a:%a %d %b %Y}, {a:%H:%M}–{b:%H:%M} IST"


def _do(fn, *args, success: str, **kw) -> None:
    try:
        fn(*args, **kw)
    except ApprovalError as e:
        st.session_state["hitl_flash"] = ("error", str(e))
    else:
        st.session_state["hitl_flash"] = ("success", success)
    st.rerun()


def _stamp(v: ActionView) -> str:
    a = v.action
    when = a.executed_at or a.decided_at
    sub = f"{when:%d %b %Y}" if when else ""
    if a.reviewer:
        sub = f"{sub} · {a.reviewer}" if sub else a.reviewer
    if v.status == "EXECUTED":
        return stamp("Approved", "approved", sub)
    if v.status in ("APPROVED", "RETRYING"):
        return stamp("Approved", "ink", "being filed")
    if v.status == "REJECTED":
        return stamp("Rejected", "red", sub)
    if v.status == "FAILED":
        return stamp("Not filed", "red", "retry below")
    return stamp("Awaiting approval", "pending", "older than 48 h" if v.stale() else "")


def _email_html(v: ActionView) -> str:
    subject, _, body = v.preview.partition("\n\n")
    body_html = esc(body)
    mc = (v.args.get("market_context") or "").strip()
    if mc and esc(mc) in body_html:
        body_html = body_html.replace(esc(mc), f"<mark>{esc(mc)}</mark>", 1)
    head = kv([("To", "Advisor desk"), ("Subject", subject.removeprefix("Subject: "))])
    return f'<div class="io-mail">{head}<div class="text">{body_html}</div></div>'


def _preview(v: ActionView) -> None:
    a = v.args
    if v.tool == CREATE_HOLD:
        html_block(
            kv([
                ("Title", v.preview.splitlines()[0].removeprefix("📅 ").strip()),
                ("When", _when(a.get("start_ist"), a.get("end_ist"))),
                ("Held as", f"Tentative, version {a.get('version', 1)}"),
            ])
        )  # fmt: skip
    elif v.tool == GMAIL_DRAFT:
        html_block(_email_html(v))
        html_block('<p class="io-foot-cap">Highlighted: Market Context from this week\'s '
                   "review pulse, so the advisor knows customer sentiment.</p>")  # fmt: skip
    elif v.tool == DOCS_APPEND:
        html_block(f'<div class="io-quote io-mono">{esc(v.preview)}</div>')
    else:
        html_block(f'<p class="io-body">{esc(v.preview.removeprefix("🗑️ ").strip())}</p>')


def _controls(v: ActionView, reviewer: str) -> None:
    label = TOOL_LABEL.get(v.tool, v.tool)
    if v.status == "FAILED":
        if st.button("Retry", key=f"retry_{v.id}", type="primary", icon=":material/replay:"):
            _do(actions.retry, v.id, reviewer, success=f"{label} filed on retry.")
        return
    if v.status != "PENDING":
        return
    with st.container(horizontal=True):
        if st.button("Approve", key=f"approve_{v.id}", type="primary",
                     disabled=bool(v.blocked_by_precheck), icon=":material/check:"):  # fmt: skip
            _do(actions.approve, v.id, reviewer, success=f"Approved: {label}.")
        if v.tool == GMAIL_DRAFT:
            with st.popover("Edit email", icon=":material/edit:"):
                with st.form(f"edit_{v.id}", border=False):
                    summary = st.text_area("Call summary", v.args.get("call_summary") or "")
                    mc = st.text_area("Market Context", v.args.get("market_context") or "")
                    if st.form_submit_button("Save edits", type="primary"):
                        _do(
                            actions.edit, v.id, reviewer,
                            {"call_summary": summary, "market_context": mc},
                            success="Edits saved. Personal details are masked automatically.",
                        )  # fmt: skip
        with st.popover("Reject", icon=":material/block:"):
            reason = st.text_input("Reason", key=f"reason_{v.id}")
            if st.button("Reject", key=f"reject_{v.id}"):
                _do(actions.reject, v.id, reviewer, reason, success=f"Rejected: {label}.")
    if v.blocked_by_precheck:
        html_block(f'<p class="io-foot-cap">Can\'t be approved yet: {esc(v.blocked_by_precheck)}'
                   "</p>")  # fmt: skip


def _annexure(v: ActionView, letter: str, reviewer: str) -> None:
    title = esc(TOOL_LABEL.get(v.tool, v.tool))
    tone = "iris" if v.tool == GMAIL_DRAFT else "brand"
    with card(f"ann-{v.id}"):
        html_block(
            f'<div class="io-annex-head"><div class="io-cardhead" style="margin:0">'
            f"{icon(TOOL_ICON.get(v.tool, 'notes'), tone, small=True)}<h3>Annexure {letter}. "
            f"{title}<span>({esc(TOOL_SUB.get(v.tool, ''))})</span></h3></div>{_stamp(v)}</div>"
        )
        _preview(v)
        if v.status in ("APPROVED", "RETRYING") and (waiting := actions.waiting_on(v.id)):
            html_block(f'<p class="io-foot-cap">Files after annexure step '
                       f'{esc(", ".join(waiting))}.</p>')  # fmt: skip
        _controls(v, reviewer)


def _focus(code: str) -> None:
    st.session_state["focus_code"] = code


def _queue_list(rows: list[dict], selected: str) -> None:
    for r in rows:
        if r["pending"]:
            badge = tag(f"{r['pending']} to approve", "amber")
        elif r["failed"]:
            badge = tag(f"{r['failed']} not filed", "red")
        else:
            badge = tag("Filed", "sage")
        is_sel = r["code"] == selected
        with card(f"q-{r['code']}", tone="brand" if is_sel else ""):
            html_block(
                f'<div class="io-mono" style="font-weight:700">{esc(r["code"])}</div>'
                f'<div class="io-foot-cap" style="margin:.15rem 0 .35rem">{esc(r["topic"])}, '
                f"{esc(r['slot'])}</div>{badge}"
            )
            st.button(
                "Open" if not is_sel else "Open now", key=f"hitl_open_{r['code']}",
                disabled=is_sel, type="tertiary", on_click=_focus, args=(r["code"],),
            )  # fmt: skip


def _detail(row: dict, reviewer: str) -> None:
    code = row["code"]
    label, tone = BOOKING_STATUS.get(row["booking_status"], (row["booking_status"].title(), "ink"))
    filed = tag(f"{row['executed']} of {row['total']} filed", "muted")
    html_block(
        '<div class="io-refblock"><div class="lbl">Booking code</div>'
        f'<div class="code">{esc(code)}</div><div class="row">{esc(row["topic"])}, '
        f"{esc(row['slot'])}</div>{tag(label, tone)} "
        f"{filed}</div>"
    )
    if row["pending"]:
        if st.button(f"Approve all for {code}", type="primary", key="hitl_approve_all",
                     icon=":material/done_all:"):  # fmt: skip
            _, errors = actions.approve_all(code, reviewer)
            st.session_state["hitl_flash"] = (
                ("warning", "Some items weren't approved: " + "; ".join(errors.values()))
                if errors else ("success", f"Approved all follow-ups for {code}.")
            )  # fmt: skip
            st.rerun()
    elif row["executed"] == row["total"]:
        note("The booking code is now entered in the pre-booking notes register below.",
             "sage", title="All follow-ups done.")  # fmt: skip
    for i, v in enumerate(actions.actions_for(code)):
        _annexure(v, chr(ord("A") + i), reviewer)


def register() -> None:
    """Pre-booking notes register: one line per approved booking, carrying its booking code and
    the review pulse that briefed the call (the M2 <-> M3 link)."""
    with card("register"):
        card_head("Pre-booking notes register", "One line per approved booking",
                  icon_name="notes")  # fmt: skip
        _register_table()


def _register_table() -> None:
    lines = notes.booking_lines()
    if not lines:
        html_block('<p class="io-foot-cap">No entries yet. Approve a booking\'s notes line and it '
                   "is entered here with its booking code.</p>")  # fmt: skip
        return
    head = "".join(f"<th scope='col'>{c}</th>" for c in REGISTER_COLS)
    body = []
    for ln in lines:
        cells = [p.strip() for p in ln.split("|")][: len(REGISTER_COLS)]
        cells += [""] * (len(REGISTER_COLS) - len(cells))
        tds = "".join(
            f'<td class="code">{esc(c)}</td>' if i == 3 else f"<td>{esc(c)}</td>"
            for i, c in enumerate(cells)
        )
        body.append(f"<tr>{tds}</tr>")
    html_block(f'<table class="io-register"><thead><tr>{head}</tr></thead>'
               f'<tbody>{"".join(body)}</tbody></table>')  # fmt: skip


def render() -> None:
    masthead(
        "Approvals",
        "Nothing reaches the advisor's calendar, notes or inbox until it is approved here. "
        "Emails are drafted, never sent.",
        "Admin portal",
    )
    if flash := st.session_state.pop("hitl_flash", None):
        getattr(st, flash[0])(flash[1])

    rows = actions.queue()
    if not rows:
        empty_state(
            "No actions yet",
            "When a call ends, its calendar hold, notes line and advisor email draft arrive here "
            "for approval.",
            cta="Book an advisor call", page=BOOK, key="hitl_empty_cta",
        )  # fmt: skip
        register()
        return

    todo = [r for r in rows if r["pending"] or r["failed"] or r["stale"]]
    shown = todo or rows
    codes = [r["code"] for r in shown]
    focus = st.session_state.get("focus_code")
    code = focus if focus in codes else codes[0]

    left, right = st.columns([1, 2.4], gap="large")
    with left:
        heading(f"Waiting ({len(todo)})" if todo else "All bookings")
        _queue_list(shown, code)
        if todo and len(rows) > len(todo):
            done = [r for r in rows if r not in todo]
            with st.expander(f"Filed ({len(done)})"):
                _queue_list(done, code)
    with right, card("detail"):
        _detail(next(r for r in rows if r["code"] == code), DEFAULT_REVIEWER)
    html_block('<div style="height:1.2rem"></div>')
    register()


def render_notes() -> None:
    """Retired standalone notes page (kept for old links); the register lives on Approvals."""
    masthead("Pre-booking notes", "The advisor's working doc.", "Admin portal")
    register()
