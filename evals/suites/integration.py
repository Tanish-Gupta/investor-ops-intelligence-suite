"""Eval 4 — Integration: state persistence, HITL gate, Market Context (docs/evals.md §4).

One scripted text-mode call (pulse from the nominee fixture is the latest pulse) runs through the
real end-of-call hook, so the MCP actions are proposed exactly as in the app. Writes are counted
on the mock backends to prove nothing executes before approval.
"""

from __future__ import annotations

import re
from datetime import datetime
from email import policy
from email.parser import BytesParser
from pathlib import Path
from zoneinfo import ZoneInfo

from config.settings import get_settings
from core import pii
from evals.common import Check, Metric, SuiteResult, ratio

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "reviews_fixture_nominee.csv"
CODE_RE = re.compile(r"^NL-[A-HJ-NP-Z]\d{3}$")
SCRIPT = ("Book a call about nominee updates tomorrow afternoon", "1", "yes")
FALLBACK_SCRIPT = ("book a nominee call", "monday morning", "1", "yes")
EVAL_NOW = datetime(2026, 10, 3, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata"))  # mock calendar week


def _writes(bundle) -> int:
    cal = sum(n for k, n in bundle.calendar.calls.items() if k != "list_busy")
    return cal + sum(bundle.docs.calls.values()) + sum(bundle.gmail.calls.values())


def _call(script: tuple[str, ...]) -> tuple[str | None, object, list[str]]:
    from pillar_b_voice.agent import VoiceSession

    s = VoiceSession(now=lambda: EVAL_NOW)
    turns = [s.start()] + [s.handle(u) for u in script]
    s.end()
    codes = [t.booking_code for t in turns if t.booking_code]
    return (codes[-1] if codes else None), s, [t.text for t in turns]


def _artifacts(code: str) -> dict[str, str]:
    art = get_settings().artifacts_dir
    notes = art / "notes.md"
    ics = sorted((art / "holds").glob(f"{code}-*.ics"))
    eml = sorted((art / "drafts").glob(f"{code}-*.eml"))
    return {
        "notes": notes.read_text(encoding="utf-8") if notes.exists() else "",
        "ics": ics[-1].read_text(encoding="utf-8") if ics else "",
        "eml": eml[-1].read_text(encoding="utf-8") if eml else "",
    }


def _fingerprint(code: str) -> tuple:
    from core import state

    art = get_settings().artifacts_dir
    files = sorted(p.name for p in art.rglob("*") if p.is_file() and code in p.name)
    notes = (art / "notes.md").read_text(encoding="utf-8") if (art / "notes.md").exists() else ""
    return (
        tuple(files),
        notes.count(code),
        len(state.list_actions(booking_code=code)),
        len(state.list_bookings()),
    )


_IDENTITY = ("event_id", "draft_id", "line", "doc", "subject", "title")
_WRITE_FLAGS = ("created", "appended")


def _same_effect(stored: dict, replayed: dict) -> bool:
    """A replayed tool call must hit the same object and report that it wrote nothing new."""
    same_ids = all(stored.get(k) == replayed.get(k) for k in _IDENTITY if k in stored)
    no_new_write = not any(replayed.get(k) for k in _WRITE_FLAGS)
    return same_ids and no_new_write


def run() -> SuiteResult:
    from core import state
    from pillar_c_mcp import actions
    from pillar_c_mcp.client import call_tool, get_bundle
    from pillar_m2_pulse.pulse import run_pulse

    res = SuiteResult("integration", "Integration (state, HITL, Market Context)")
    add = res.checks.append
    pulse = run_pulse(FIXTURE, use_llm=False)
    bundle = get_bundle()

    code, session, transcript = _call(SCRIPT)
    script = SCRIPT
    if code is None:  # the agent may need an explicit day; keep the eval about integration
        code, session, transcript = _call(FALLBACK_SCRIPT)
        script = FALLBACK_SCRIPT
    add(
        Check(
            "I1",
            "Booking code format NL-X999",
            bool(code and CODE_RE.match(code)),
            f"{code} via script {list(script)}",
            data={"transcript": transcript},
        )
    )
    if not code:
        res.error = "no booking was made by the scripted call"
        return res

    pending = actions.actions_for(code)
    writes_before = _writes(bundle)
    gate = len(pending) == 3 and all(a.status == "PENDING" for a in pending) and writes_before == 0
    add(
        Check(
            "I2",
            "HITL gate: 3 PENDING actions, 0 backend writes before approval",
            gate,
            f"{[(a.tool, a.status) for a in pending]} · writes={writes_before}",
        )
    )

    actions.approve_all(code, "eval-reviewer")
    done = actions.actions_for(code)
    executed = len(done) == 3 and all(a.status == "EXECUTED" for a in done)
    booking = state.get_booking(code)
    add(
        Check(
            "I3",
            "Approve-all executes all 3 actions",
            executed,
            f"{[(a.tool, a.status) for a in done]} · booking {booking.status if booking else None}",
        )
    )

    art = _artifacts(code)
    msg = BytesParser(policy=policy.default).parsebytes(art["eml"].encode("utf-8"))
    body = msg.get_body(preferencelist=("plain",))
    body_text = body.get_content() if body is not None else ""
    summary = re.search(r"^SUMMARY:(.*)$", art["ics"], re.M)
    persisted = {
        "notes.md": code in art["notes"],
        "calendar .ics title": bool(summary and code in summary.group(1)),
        "email subject": code in str(msg.get("Subject", "")),
    }
    add(
        Check(
            "I4",
            "State persistence: same booking code in Notes/Doc, Calendar and Email",
            all(persisted.values()),
            ", ".join(f"{k}={'✓' if v else '✗'}" for k, v in persisted.items()),
        )
    )

    mc = {
        "'Market Context'": "Market Context" in body_text,
        "top theme": bool(pulse.top_theme) and pulse.top_theme in body_text,
        "pulse id": pulse.pulse_id in body_text,
        "pulse id in notes line": pulse.pulse_id in art["notes"],
    }
    add(
        Check(
            "I5",
            "Advisor email carries the Weekly Pulse Market Context",
            all(mc.values()),
            ", ".join(f"{k}={'✓' if v else '✗'}" for k, v in mc.items()),
            data={"email_body": body_text},
        )
    )

    leaks = {
        k: [e.entity_type for e in pii.detect(v)]
        for k, v in (("notes", art["notes"]), ("ics", art["ics"]), ("email body", body_text))
    }
    leaks = {k: v for k, v in leaks.items() if v}
    caller_masked = "Caller: [REDACTED]" in body_text
    add(
        Check(
            "I6",
            "No PII in notes / calendar / email; caller shown as [REDACTED]",
            not leaks and caller_masked,
            f"PII found: {leaks or 'none'} · caller masked: {caller_masked}",
        )
    )

    before = _fingerprint(code)
    reproposed = actions.propose_for_booking(session.results[-1])
    actions.approve_all(code, "eval-reviewer")
    for a in actions.actions_for(code):
        actions.execute(a.id)
    replay = [
        _same_effect(a.result or {}, call_tool(a.tool, a.args)) for a in actions.actions_for(code)
    ]
    after = _fingerprint(code)
    idem = before == after and all(replay)
    add(
        Check(
            "I7",
            "Idempotency: re-propose / re-approve / re-execute / replayed tool calls",
            idem,
            f"rows+files unchanged={before == after} · replayed calls dedup to same object="
            f"{sum(replay)}/{len(replay)} · re-propose returned {len(reproposed)} actions",
            data={"before": list(before), "after": list(after)},
        )
    )

    p = sum(c.passed for c in res.checks)
    res.metrics = [
        Metric("Integration checks", ratio(p, len(res.checks)), "all", p == len(res.checks) == 7)
    ]
    res.notes.append(
        f"Pulse {pulse.pulse_id} (top theme {pulse.top_theme}) from {FIXTURE.name}; "
        "backends: local mock adapters (same FastMCP tools as Google mode)."
    )
    return res
