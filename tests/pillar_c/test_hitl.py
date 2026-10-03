"""Phase 6 HITL tests: voice call → PENDING actions → human approval → MCP execution, with
ordering, idempotency, reschedule/cancel plans, retries/backoff, compensation and edit rules."""

from __future__ import annotations

import email
import json
from datetime import timedelta
from email import policy

import pytest

from core import notes, state
from pillar_b_voice.agent import VoiceSession
from pillar_c_mcp import actions, plan
from pillar_c_mcp.actions import ApprovalError
from pillar_c_mcp.tool_gate import check_job
from tests.pillar_m2.conftest import NOMINEE

from .conftest import fixed_now, run, writes

BOOK = ("book a nominee call", "monday morning", "1", "yes")


def _tools(code: str) -> list[tuple[str, str]]:
    return [(v.tool, v.status) for v in actions.actions_for(code)]


def _by_tool(code: str, tool: str, tag: str | None = None) -> actions.ActionView:
    return next(v for v in actions.actions_for(code) if v.tool == tool and tag in (None, v.tag))


def _eml(path: str) -> email.message.EmailMessage:
    with open(path, "rb") as fh:
        return email.message_from_bytes(fh.read(), policy=policy.default)


# --- happy path: state persistence across M2 + M3 ------------------------------------------------
def test_voice_call_to_approved_artifacts_share_code_and_pulse(call, hitl, workspace):
    from pillar_m2_pulse.pulse import run_pulse

    pulse = run_pulse(NOMINEE)
    code = call(*BOOK, pulse="latest")
    assert _tools(code) == [
        (plan.CREATE_HOLD, "PENDING"),
        (plan.DOCS_APPEND, "PENDING"),
        (plan.GMAIL_DRAFT, "PENDING"),
    ]
    assert writes(hitl) == 0  # HITL: nothing written before approval
    for v in actions.actions_for(code):
        assert v.prechecks and not v.blocked_by_precheck, v.prechecks
    draft = _by_tool(code, plan.GMAIL_DRAFT)
    assert pulse.pulse_id in draft.args["market_context"]
    assert "Nominee Updates" in draft.args["market_context"]
    assert state.get_booking(code).status == "TENTATIVE"

    _, errors = actions.approve_all(code, "ops-reviewer")
    assert not errors
    assert all(s == "EXECUTED" for _, s in _tools(code))
    assert writes(hitl) == 3
    assert state.get_booking(code).status == "CONFIRMED"

    line = next(ln for ln in notes.booking_lines() if code in ln)
    assert line.endswith(f"| {code} | tentative | {pulse.pulse_id}")
    hold = hitl.calendar.holds()
    assert any(h["code"] == code and h["status"] == "tentative" for h in hold)
    ics = (workspace / "artifacts" / "holds" / f"{code}-v1.ics").read_text()
    assert f"X-BOOKING-CODE:{code}" in ics
    msg = _eml(_by_tool(code, plan.GMAIL_DRAFT).result["path"])
    body = msg.get_content()
    assert code in msg["Subject"] and "Market Context" in body and pulse.pulse_id in body
    assert "Caller: [REDACTED]" in body
    events = {a.event for a in state.list_audit(code)}
    assert "booking_confirmed" in events


def test_no_pulse_uses_documented_line(call):
    code = call(*BOOK, pulse=None)
    draft = _by_tool(code, plan.GMAIL_DRAFT)
    assert "no Weekly Pulse" in draft.args["market_context"]
    assert draft.prechecks["market_context"]["ok"] is True
    actions.approve_all(code)
    assert next(ln for ln in notes.booking_lines() if code in ln).endswith("| no-pulse")


def test_order_is_enforced_and_reproposal_is_idempotent(hitl):
    s = VoiceSession(pulse=None, now=fixed_now)
    run(s, *BOOK)
    s.end()
    res = s.results[-1]
    code = res.booking_code
    assert len(actions.propose_for_booking(res)) == 3
    assert len(actions.actions_for(code)) == 3  # same idempotency keys → no duplicates

    gmail = _by_tool(code, plan.GMAIL_DRAFT)
    actions.approve(gmail.id, "r1")
    assert state.get_action(gmail.id).status == "APPROVED"
    assert len(actions.waiting_on(gmail.id)) == 2 and writes(hitl) == 0
    actions.approve(_by_tool(code, plan.CREATE_HOLD).id, "r1")
    assert writes(hitl) == 1 and state.get_action(gmail.id).status == "APPROVED"
    actions.approve(_by_tool(code, plan.DOCS_APPEND).id, "r1")
    assert all(s == "EXECUTED" for _, s in _tools(code)) and writes(hitl) == 3
    with pytest.raises(ApprovalError):
        actions.approve(gmail.id, "r1")  # already executed


# --- reschedule & cancel plans -------------------------------------------------------------------
def test_reschedule_creates_v2_then_releases_v1(call, hitl):
    code = call(*BOOK)
    actions.approve_all(code)
    v1 = _by_tool(code, plan.CREATE_HOLD, "1").result["event_id"]
    assert call(f"reschedule {code}", "tuesday 3 pm", "1", "yes") == code
    new = [v for v in actions.actions_for(code) if v.tag == "2"]
    assert [v.tool for v in new] == [
        plan.CREATE_HOLD,
        plan.DELETE_HOLD,
        plan.DOCS_APPEND,
        plan.GMAIL_DRAFT,
    ]
    assert new[1].args["event_id"] == v1 and new[0].args["version"] == 2
    actions.approve_all(code)
    holds = {h["event_id"]: h["status"] for h in hitl.calendar.holds()}
    assert holds[v1] == "cancelled"
    assert holds[_by_tool(code, plan.CREATE_HOLD, "2").result["event_id"]] == "tentative"
    assert any(ln.endswith(" | rescheduled | no-pulse") for ln in notes.booking_lines())
    assert "Reschedul" in _eml(_by_tool(code, plan.GMAIL_DRAFT, "2").result["path"])["Subject"]


def test_rejected_new_hold_keeps_old_hold(call, hitl):
    code = call(*BOOK)
    actions.approve_all(code)
    call(f"reschedule {code}", "tuesday 3 pm", "1", "yes")
    create = _by_tool(code, plan.CREATE_HOLD, "2")
    delete = _by_tool(code, plan.DELETE_HOLD, "2")
    actions.approve(delete.id, "r1")
    actions.reject(create.id, "r1", "advisor unavailable that day")
    assert state.get_action(delete.id).status == "REJECTED"
    assert json.loads(state.get_action(delete.id).result_json)["reason"].startswith("skipped")
    assert hitl.calendar.calls["delete_hold"] == 0
    assert "booking_flagged" in {a.event for a in state.list_audit(code)}


def test_cancel_plan_releases_hold(call, hitl):
    code = call(*BOOK)
    actions.approve_all(code)
    call("I want to cancel my booking", code, "yes")
    tools = [v.tool for v in actions.actions_for(code) if v.tag == "cancel"]
    assert tools == [plan.DELETE_HOLD, plan.DOCS_APPEND, plan.GMAIL_DRAFT]
    actions.approve_all(code)
    assert all(h["status"] == "cancelled" for h in hitl.calendar.holds() if h["code"] == code)
    assert state.get_booking(code).status == "CANCELLED"
    assert any(code in ln and "| cancelled |" in ln for ln in notes.booking_lines())


# --- failures: retry with backoff, compensation, slot race ---------------------------------------
def test_transient_failure_backs_off_then_compensates(call, hitl, monkeypatch):
    code = call(*BOOK)
    calls = {"n": 0}

    def flaky(**kw):
        calls["n"] += 1
        raise OSError("calendar unreachable")

    monkeypatch.setattr(hitl.calendar, "create_hold", flaky)
    now = state.now()
    actions.approve_all(code, now=now)
    hold = _by_tool(code, plan.CREATE_HOLD)
    assert hold.status == "RETRYING" and calls["n"] == 1
    assert actions.run_due(now + timedelta(seconds=1)) == []  # backoff not elapsed
    t = now
    for delay in actions.BACKOFF_S:
        t += timedelta(seconds=delay + 1)
        actions.run_due(t)
    hold = _by_tool(code, plan.CREATE_HOLD)
    assert hold.status == "FAILED" and calls["n"] == len(actions.BACKOFF_S) + 1
    assert state.get_booking(code).status == "NEEDS_ATTENTION"
    comp = [v for v in actions.actions_for(code) if v.plan == "compensation"]
    assert [v.tool for v in comp] == [plan.DOCS_APPEND, plan.GMAIL_DRAFT]
    assert comp[1].args["template"] == "ops_alert" and comp[0].args["status"] == "hold_failed"

    monkeypatch.undo()
    actions.retry(hold.id, "r1")
    assert state.get_action(hold.id).status == "EXECUTED"


def test_permanent_failure_fails_fast(call, hitl, monkeypatch):
    class Http400(Exception):
        resp = type("R", (), {"status": 400})()

    def bad(**kw):
        raise Http400("bad request")

    code = call(*BOOK)
    monkeypatch.setattr(hitl.calendar, "create_hold", bad)
    actions.approve_all(code)
    hold = _by_tool(code, plan.CREATE_HOLD)
    assert hold.status == "FAILED" and hold.result["retryable"] is False
    assert state.get_booking(code).status == "NEEDS_ATTENTION"


def test_slot_taken_before_approval_blocks_approve(call, hitl):
    code = call(*BOOK)
    hold = _by_tool(code, plan.CREATE_HOLD)
    hitl.calendar.create_hold(
        code="NL-Z999",
        topic="KYC/Onboarding",
        kind="booking",
        version=1,
        start_ist=hold.args["start_ist"],
        end_ist=hold.args["end_ist"],
    )
    with pytest.raises(ApprovalError, match="slot_free"):
        actions.approve(hold.id, "r1")
    assert state.get_action(hold.id).status == "PENDING"
    assert _by_tool(code, plan.CREATE_HOLD).prechecks["slot_free"]["ok"] is False


# --- reviewer rules ------------------------------------------------------------------------------
def test_edit_rules_and_audit(call):
    code = call(*BOOK)
    draft = _by_tool(code, plan.GMAIL_DRAFT)
    actions.edit(draft.id, "r1", {"call_summary": "Caller asked about nominee, mail me x@y.com"})
    edited = _by_tool(code, plan.GMAIL_DRAFT)
    assert "x@y.com" not in edited.args["call_summary"]
    assert "action_edited" in {a.event for a in state.list_audit(draft.id)}
    with pytest.raises(ApprovalError, match="advice"):
        actions.edit(draft.id, "r1", {"market_context": "You should buy this fund now"})
    with pytest.raises(ApprovalError, match="read-only"):
        actions.edit(draft.id, "r1", {"code": "NL-B222"})
    with pytest.raises(ApprovalError):
        actions.edit(_by_tool(code, plan.CREATE_HOLD).id, "r1", {"call_summary": "x"})
    actions.approve_all(code)
    assert "nominee" in _eml(_by_tool(code, plan.GMAIL_DRAFT).result["path"]).get_content()


def test_reject_requires_reason_and_unblocks_later_steps(call, hitl):
    code = call(*BOOK)
    hold = _by_tool(code, plan.CREATE_HOLD)
    with pytest.raises(ApprovalError, match="reason"):
        actions.reject(hold.id, "r1", "  ")
    actions.approve(_by_tool(code, plan.DOCS_APPEND).id, "r1")
    assert writes(hitl) == 0  # waits for the hold decision
    actions.reject(hold.id, "r1", "duplicate request")
    assert _by_tool(code, plan.DOCS_APPEND).status == "EXECUTED"
    assert state.get_booking(code).status == "TENTATIVE"  # not confirmed without a hold


def test_queue_rows_and_stale_flag(call):
    code = call(*BOOK)
    rows = actions.queue()
    assert rows[0]["code"] == code and rows[0]["pending"] == 3 and not rows[0]["stale"]
    later = state.now() + timedelta(hours=49)
    assert actions.queue(now=later)[0]["stale"]


# --- tool gate -----------------------------------------------------------------------------------
def test_gate_rules():
    args = {
        "template": "booking",
        "code": "NL-A123",
        "topic": "Nominee Updates",
        "call_summary": "ok",
    }
    assert check_job(plan.GMAIL_DRAFT, args, status="APPROVED", plan_args=args).approved
    edited = {**args, "call_summary": "edited text"}
    assert check_job(plan.GMAIL_DRAFT, edited, status="APPROVED", plan_args=args).approved
    assert check_job("gmail_send", args, status="APPROVED", plan_args=args).rule == "unknown_tool"
    assert check_job(plan.GMAIL_DRAFT, args, status="PENDING", plan_args=args).rule == (
        "not_approved"
    )
    leak = {**args, "call_summary": "PAN ABCDE1234F"}
    assert check_job(plan.GMAIL_DRAFT, leak, status="APPROVED", plan_args=args).rule == "pii"
    moved = {**args, "code": "NL-B222"}
    assert check_job(plan.GMAIL_DRAFT, moved, status="APPROVED", plan_args=args).rule == (
        "plan_mismatch"
    )
