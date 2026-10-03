"""HITL layer + outbox (Pillar C): every MCP write waits for a human in the Approval Center.

Lifecycle (M3's transactional outbox with one extra gate):

    PENDING ──approve──▶ APPROVED ──tool ok──▶ EXECUTED
       │                    │ retryable error ──▶ RETRYING ──(5s,15s,60s,5m,15m)──▶ EXECUTED/FAILED
       └──reject──▶ REJECTED └ permanent error ──▶ FAILED ──retry──▶ APPROVED

* `propose_for_booking(result)` is the voice agent's end-of-call hook: it turns the booking
  outcome into a plan (`plan.py`) and queues one PENDING action per write step. Nothing touches
  the calendar, notes or email until a reviewer approves.
* Actions of one booking code run strictly in plan order: an action waits while any earlier
  action of the same code is still PENDING / APPROVED / RETRYING.
* Every execution goes through the ToolGate, then the FastMCP client.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from config.settings import get_settings
from core import guardrails, pii, state
from core.state import Action, ActionStatus, BookingStatus

from .client import ToolCallError, call_tool
from .plan import (
    CREATE_HOLD,
    DELETE_HOLD,
    DOCS_APPEND,
    EDITABLE_FIELDS,
    GMAIL_DRAFT,
    LIST_BUSY,
    MAX_MARKET_CONTEXT,
    MAX_SUMMARY,
    Plan,
    booking_plan,
    cancel_plan,
    compensation_plan,
    hold_title,
    prebooking_line,
    reschedule_plan,
    slot_human,
)
from .templates import render
from .tool_gate import RUNNABLE, check_job, strings

_log = logging.getLogger(__name__)

BACKOFF_S = (5, 15, 60, 300, 900)
STALE_AFTER = timedelta(hours=48)
OPEN = {ActionStatus.PENDING.value, ActionStatus.APPROVED.value, ActionStatus.RETRYING.value}
CODE_RE = state.BOOKING_CODE_RE
NO_PULSE_MARKERS = ("no Weekly Pulse", "Not available this week")


class ApprovalError(ValueError):
    """A reviewer action is not allowed (wrong status, blocked pre-check, illegal edit…)."""


# --- views ---------------------------------------------------------------------------------
@dataclass
class ActionView:
    action: Action
    args: dict[str, Any]
    meta: dict[str, Any]
    result: dict[str, Any] | None

    @property
    def id(self) -> str:
        return self.action.action_id

    @property
    def tool(self) -> str:
        return self.action.tool

    @property
    def status(self) -> str:
        return self.action.status

    @property
    def seq(self) -> int:
        return int(self.meta.get("seq", 0))

    @property
    def plan(self) -> str:
        return self.meta.get("plan", "")

    @property
    def tag(self) -> str:
        return str(self.meta.get("tag", ""))

    @property
    def prechecks(self) -> dict[str, dict[str, Any]]:
        return self.meta.get("prechecks", {})

    @property
    def blocked_by_precheck(self) -> list[str]:
        return [k for k, v in self.prechecks.items() if v.get("ok") is False]

    @property
    def proposed_at(self) -> datetime | None:
        ts = self.meta.get("proposed_at")
        return datetime.fromisoformat(ts) if ts else None

    def age(self, now: datetime | None = None) -> timedelta:
        start = self.proposed_at
        return ((now or state.now()) - start) if start else timedelta(0)

    def stale(self, now: datetime | None = None) -> bool:
        return self.status == ActionStatus.PENDING.value and self.age(now) > STALE_AFTER

    @property
    def preview(self) -> str:
        return preview(self.tool, self.args, self.action.booking_code or "")


def view(a: Action) -> ActionView:
    payload = state.loads(a.payload_json) or {}
    return ActionView(
        a, payload.get("args", {}), payload.get("meta", {}), state.loads(a.result_json)
    )


def actions_for(code: str) -> list[ActionView]:
    return sorted((view(a) for a in state.list_actions(booking_code=code)), key=lambda v: v.seq)


def all_views() -> list[ActionView]:
    return sorted(
        (view(a) for a in state.list_actions()),
        key=lambda v: (v.action.booking_code or "", v.seq),
    )


def list_pending() -> list[ActionView]:
    return [v for v in all_views() if v.status == ActionStatus.PENDING.value]


def queue(now: datetime | None = None) -> list[dict[str, Any]]:
    """One row per booking code for the Approval Center table."""
    rows: dict[str, dict[str, Any]] = {}
    for v in all_views():
        code = v.action.booking_code or "—"
        row = rows.setdefault(
            code,
            {"code": code, "pending": 0, "open": 0, "executed": 0, "failed": 0, "total": 0,
             "stale": False, "oldest_pending_h": 0.0, "pulse_id": None},
        )  # fmt: skip
        row["total"] += 1
        row["pending"] += v.status == ActionStatus.PENDING.value
        row["open"] += v.status in OPEN
        row["executed"] += v.status == ActionStatus.EXECUTED.value
        row["failed"] += v.status == ActionStatus.FAILED.value
        row["stale"] = row["stale"] or v.stale(now)
        row["pulse_id"] = row["pulse_id"] or v.args.get("pulse_id")
        if v.status == ActionStatus.PENDING.value:
            hours = round(v.age(now).total_seconds() / 3600, 1)
            row["oldest_pending_h"] = max(row["oldest_pending_h"], hours)
    tz = get_settings().tz
    for code, row in rows.items():
        b = state.get_booking(code)
        row["topic"] = b.topic if b else None
        row["slot"] = (
            slot_human(b.slot_start_ist.astimezone(tz)) if b and b.slot_start_ist else None
        )
        row["booking_status"] = b.status if b else None
    return sorted(rows.values(), key=lambda r: (-r["open"], r["code"]))


# --- previews & pre-checks ------------------------------------------------------------------
def preview(tool: str, args: dict[str, Any], code: str) -> str:
    if tool == CREATE_HOLD:
        title = hold_title(
            args.get("topic", ""), args.get("code", code), args.get("kind", "booking")
        )
        window = f"{args.get('start_ist')} → {args.get('end_ist')}"
        return f"📅 {title}\n{window} · tentative · v{args.get('version', 1)}"
    if tool == DELETE_HOLD:
        return f"🗑️ Release calendar hold `{args.get('event_id')}` for {code}"
    if tool == DOCS_APPEND:
        return prebooking_line(
            args.get("date", ""), args.get("topic", ""), args.get("slot", ""),
            args.get("code", code), args.get("status", ""), args.get("pulse_id"),
        )  # fmt: skip
    if tool == GMAIL_DRAFT:
        subject, body = render(
            args.get("template", "booking"), code=args.get("code", code),
            topic=args.get("topic", ""), slot=args.get("slot"),
            call_summary=args.get("call_summary"), market_context=args.get("market_context"),
            pulse_id=args.get("pulse_id"),
        )  # fmt: skip
        return f"Subject: {subject}\n\n{body}"
    return str(args)


def _check(ok: bool | None, detail: str) -> dict[str, Any]:
    return {"ok": ok, "detail": detail}


def slot_conflicts(code: str, start_ist: str, end_ist: str) -> list[dict[str, Any]]:
    """Busy intervals (via the read-only MCP tool) other than this booking's own hold."""
    busy = call_tool(LIST_BUSY, {"start_ist": start_ist, "end_ist": end_ist}).get("busy", [])
    return [b for b in busy if b.get("code") != code]


def run_prechecks(
    tool: str, args: dict[str, Any], code: str, *, check_slot: bool = True
) -> dict[str, dict[str, Any]]:
    """Automatic checks shown as badges; any `ok: False` disables Approve."""
    text = preview(tool, args, code)
    out: dict[str, dict[str, Any]] = {}
    leaked = [s for s in strings(args) if pii.contains_pii(s)]
    out["pii"] = _check(not leaked, "no personal data" if not leaked else "PII found in args")

    code_ok = bool(CODE_RE.match(code)) and args.get("code", code) == code
    if tool != DELETE_HOLD:
        code_ok = code_ok and code in text
    out["booking_code"] = _check(
        code_ok, f"{code} in title/notes/subject" if code_ok else "missing"
    )

    if tool == GMAIL_DRAFT:
        mc = args.get("market_context") or ""
        pid = args.get("pulse_id")
        has_block = "Market Context" in mc
        if pid:
            ok = has_block and pid in mc
            out["market_context"] = _check(ok, f"Weekly Pulse {pid}" if ok else "block missing")
        else:
            ok = has_block or any(m in mc for m in NO_PULSE_MARKERS)
            out["market_context"] = _check(ok, "no pulse yet (documented line)")

    if tool == CREATE_HOLD and check_slot:
        try:
            clash = slot_conflicts(code, args["start_ist"], args["end_ist"])
        except ToolCallError as e:  # can't verify: warn, don't block
            out["slot_free"] = _check(None, f"could not check: {e.message[:80]}")
        else:
            out["slot_free"] = _check(not clash, "slot free" if not clash else "slot already busy")

    violations = guardrails.output_violations(text)
    out["guardrail"] = _check(not violations, "no advice language" if not violations else
                              ", ".join(violations))  # fmt: skip
    return out


# --- proposing ------------------------------------------------------------------------------
def _pulse_obj(pulse_id: str | None) -> Any:
    if not pulse_id:
        return None
    from pillar_m2_pulse.pulse import PulseResult, get_latest_pulse

    latest = get_latest_pulse()
    if latest and latest.pulse_id == pulse_id:
        return latest
    row = state.get_pulse(pulse_id)
    return PulseResult.from_row(row) if row else None


def market_context_for(pulse_id: str | None, topic: str | None) -> str:
    from pillar_m2_pulse.market_context import build_market_context

    return build_market_context(_pulse_obj(pulse_id), topic)[:MAX_MARKET_CONTEXT]


def _hold_versions(code: str, *, live_only: bool) -> list[int]:
    dead = {ActionStatus.REJECTED.value, ActionStatus.FAILED.value}
    return [
        int(v.args.get("version", 1))
        for v in actions_for(code)
        if v.tool == CREATE_HOLD and not (live_only and v.status in dead)
    ]


def current_hold_version(code: str) -> int:
    return max(_hold_versions(code, live_only=True), default=1)


def _queue(plan: Plan, *, now: datetime | None = None) -> list[Action]:
    existing = actions_for(plan.code)
    base = max((v.seq for v in existing), default=0)
    ts = (now or state.now()).isoformat()
    out: list[Action] = []
    for i, step in enumerate(plan.steps, start=1):
        checks = run_prechecks(step.tool, step.args, plan.code)
        payload = {
            "args": step.args,
            "meta": {"seq": base + i, "plan": plan.kind, "tag": plan.tag, "proposed_at": ts,
                     "plan_args": step.args, "prechecks": checks},
        }  # fmt: skip
        row, created = state.create_action(
            booking_code=plan.code, tool=step.tool, payload=payload, version=plan.tag
        )
        if created:
            state.audit("system", "action_proposed", row.action_id,
                        {"code": plan.code, "tool": step.tool, "plan": plan.kind})  # fmt: skip
        out.append(row)
    return out


def propose_for_booking(result: Any, *, now: datetime | None = None) -> list[Action]:
    """Voice-agent end-of-call hook: BookingResult → PENDING actions (no backend writes)."""
    code = result.booking_code
    tz = get_settings().tz
    booked_on = result.created_at.astimezone(tz).date()
    summary = pii.redact(result.call_summary)[:MAX_SUMMARY]
    mc = market_context_for(result.pulse_id, result.topic)
    common = {
        "code": code,
        "topic": result.topic,
        "booked_on": booked_on,
        "call_summary": summary,
        "market_context": mc,
        "pulse_id": result.pulse_id,
    }
    if result.action == "BOOK":
        plan = booking_plan(start=result.slot_start, end=result.slot_end, **common)
    elif result.action == "RESCHEDULE":
        plan = reschedule_plan(
            start=result.slot_start, end=result.slot_end,
            version=max(_hold_versions(code, live_only=False), default=1) + 1,
            previous_version=current_hold_version(code), **common,
        )  # fmt: skip
    elif result.action == "CANCEL":
        plan = cancel_plan(start=result.slot_start, version=current_hold_version(code), **common)
    else:
        raise ValueError(f"unknown booking action {result.action!r}")
    actions = _queue(plan, now=now)
    _log.info("hitl_proposed", extra={"code": code, "plan": plan.kind, "n": len(actions)})
    return actions


# --- reviewer actions -----------------------------------------------------------------------
def _require(a: Action | None, action_id: str, allowed: set[str]) -> Action:
    if a is None:
        raise ApprovalError(f"unknown action {action_id}")
    if a.status not in allowed:
        raise ApprovalError(f"{action_id} is {a.status}; allowed only when {sorted(allowed)}")
    return a


def _save(v: ActionView, **kw: Any) -> Action:
    return state.update_action(v.id, payload={"args": v.args, "meta": v.meta}, **kw)


def edit(action_id: str, reviewer: str, edited_args: dict[str, Any]) -> Action:
    """Edit free-text fields of a PENDING email draft; the diff goes to the audit log."""
    a = _require(state.get_action(action_id), action_id, {ActionStatus.PENDING.value})
    v = view(a)
    illegal = set(edited_args) - EDITABLE_FIELDS
    if illegal or v.tool != GMAIL_DRAFT:
        raise ApprovalError(
            f"read-only fields: {sorted(illegal) or 'all (not an email draft)'}; "
            f"only {sorted(EDITABLE_FIELDS)} of an email draft can be edited"
        )
    caps = {"call_summary": MAX_SUMMARY, "market_context": MAX_MARKET_CONTEXT}
    diff: dict[str, Any] = {}
    for key, raw in edited_args.items():
        new = pii.redact(" ".join(str(raw).split()))[: caps[key]]
        if guardrails.output_violations(new):
            raise ApprovalError(f"{key}: advice language is not allowed")
        if new != v.args.get(key):
            diff[key] = {"from": v.args.get(key), "to": new}
            v.args[key] = new
    if not diff:
        return a
    v.meta["prechecks"] = run_prechecks(v.tool, v.args, a.booking_code or "")
    v.meta["edited_by"] = pii.redact(reviewer)
    row = _save(v, actor=reviewer)
    state.audit(reviewer, "action_edited", action_id, diff)
    return row


def approve(
    action_id: str,
    reviewer: str = "reviewer",
    edited_args: dict[str, Any] | None = None,
    *,
    execute: bool = True,
    now: datetime | None = None,
) -> Action:
    a = _require(state.get_action(action_id), action_id, {ActionStatus.PENDING.value})
    if edited_args:
        a = edit(action_id, reviewer, edited_args)
    v = view(a)
    v.meta["prechecks"] = run_prechecks(v.tool, v.args, a.booking_code or "")
    blocked = v.blocked_by_precheck
    if blocked:
        _save(v, actor="system")
        raise ApprovalError(f"pre-checks failed for {action_id}: {', '.join(blocked)}")
    _save(v, status=ActionStatus.APPROVED, reviewer=reviewer, actor=reviewer)
    state.audit(reviewer, "action_approved", action_id, {"tool": v.tool})
    if execute:
        execute_ready(a.booking_code, now=now)
    return state.get_action(action_id)  # type: ignore[return-value]


def approve_all(
    code: str, reviewer: str = "reviewer", *, now: datetime | None = None
) -> tuple[list[Action], dict[str, str]]:
    """Approve every PENDING action of one booking code (in order), then execute them."""
    errors: dict[str, str] = {}
    for v in actions_for(code):
        if v.status == ActionStatus.PENDING.value:
            try:
                approve(v.id, reviewer, execute=False)
            except ApprovalError as e:
                errors[v.id] = str(e)
    execute_ready(code, now=now)
    return [a.action for a in actions_for(code)], errors


def reject(action_id: str, reviewer: str, reason: str, *, now: datetime | None = None) -> Action:
    reason = " ".join((reason or "").split())
    if not reason:
        raise ApprovalError("a reason is required to reject an action")
    allowed = {ActionStatus.PENDING.value, ActionStatus.APPROVED.value, ActionStatus.FAILED.value}
    a = _require(state.get_action(action_id), action_id, allowed)
    clean = pii.redact(reason)[:300]
    state.update_action(
        action_id, status=ActionStatus.REJECTED, reviewer=reviewer, result={"reason": clean},
        actor=reviewer,
    )  # fmt: skip
    state.audit(reviewer, "action_rejected", action_id, {"tool": a.tool, "reason": clean})
    if a.tool == CREATE_HOLD and a.booking_code:
        state.audit(reviewer, "booking_flagged", a.booking_code,
                    {"reason": "calendar hold rejected; booking stays as is"})  # fmt: skip
    execute_ready(a.booking_code, now=now)  # later steps may now be unblocked
    return state.get_action(action_id)  # type: ignore[return-value]


def retry(action_id: str, reviewer: str = "reviewer", *, now: datetime | None = None) -> Action:
    a = _require(state.get_action(action_id), action_id, {ActionStatus.FAILED.value})
    state.update_action(action_id, status=ActionStatus.APPROVED, reviewer=reviewer, actor=reviewer)
    state.audit(reviewer, "action_retried", action_id, {"tool": a.tool})
    execute_ready(a.booking_code, now=now)
    return state.get_action(action_id)  # type: ignore[return-value]


# --- execution (outbox worker) ----------------------------------------------------------------
def _waiting_on(v: ActionView) -> list[ActionView]:
    code = v.action.booking_code or ""
    return [b for b in actions_for(code) if b.seq < v.seq and b.status in OPEN]


def waiting_on(action_id: str) -> list[str]:
    a = state.get_action(action_id)
    return [b.id for b in _waiting_on(view(a))] if a else []


def _fail(v: ActionView, error: str, *, retryable: bool, actor: str = "system") -> Action:
    row = state.update_action(
        v.id, status=ActionStatus.FAILED, result={"error": error[:300], "retryable": retryable},
        actor=actor,
    )  # fmt: skip
    state.audit(actor, "action_failed", v.id, {"tool": v.tool, "error": error[:200]})
    if v.tool == CREATE_HOLD and v.plan in ("booking", "reschedule"):
        _compensate(v)
    return row


def _compensate(v: ActionView) -> None:
    """M3 compensation: the hold is dead → booking NEEDS_ATTENTION + notes line + ops alert."""
    code = v.action.booking_code or ""
    b = state.get_booking(code)
    if b is None or b.status == BookingStatus.CANCELLED.value:
        return
    state.set_booking_status(code, BookingStatus.NEEDS_ATTENTION, actor="system")
    tz = get_settings().tz
    start = datetime.fromisoformat(v.args["start_ist"]).astimezone(tz)
    pulse_id = b.pulse_id
    plan = compensation_plan(
        code=code, topic=b.topic, slot=slot_human(start), booked_on=state.now().date(),
        failed_tag=v.tag, market_context=market_context_for(pulse_id, b.topic), pulse_id=pulse_id,
    )  # fmt: skip
    _queue(plan)
    state.audit("system", "booking_needs_attention", code, {"failed_action": v.id})


def _after_success(v: ActionView) -> None:
    code = v.action.booking_code or ""
    if v.plan not in ("booking", "reschedule"):
        return
    same = [x for x in actions_for(code) if x.tag == v.tag and x.plan == v.plan]
    if all(x.status == ActionStatus.EXECUTED.value for x in same):
        b = state.get_booking(code)
        if b and b.status not in (BookingStatus.CANCELLED.value, BookingStatus.CONFIRMED.value):
            state.set_booking_status(code, BookingStatus.CONFIRMED, actor="system")
            state.audit("system", "booking_confirmed", code, {"plan": v.plan, "tag": v.tag})


def execute(action_id: str, *, now: datetime | None = None) -> Action:
    """Run one APPROVED/RETRYING action if it is due and not blocked by an earlier step."""
    now = now or state.now()
    a = state.get_action(action_id)
    if a is None:
        raise ApprovalError(f"unknown action {action_id}")
    if a.status not in RUNNABLE:
        return a
    if a.status == ActionStatus.RETRYING.value and a.next_attempt_at and a.next_attempt_at > now:
        return a
    v = view(a)
    if _waiting_on(v):
        return a
    code = a.booking_code or ""

    if v.tool == DELETE_HOLD and v.plan == "reschedule":
        create = next((x for x in actions_for(code) if x.tag == v.tag and x.tool == CREATE_HOLD),
                      None)  # fmt: skip
        if create and create.status in (ActionStatus.FAILED.value, ActionStatus.REJECTED.value):
            reason = "skipped: the new hold was not created, so the old hold is kept"
            state.update_action(v.id, status=ActionStatus.REJECTED, reviewer="system",
                                result={"reason": reason}, actor="system")  # fmt: skip
            state.audit("system", "action_skipped", v.id, {"reason": reason})
            return state.get_action(action_id)  # type: ignore[return-value]

    gate = check_job(v.tool, v.args, status=a.status, plan_args=v.meta.get("plan_args", {}))
    if not gate.approved:
        return _fail(v, f"gate:{gate.label}", retryable=False)

    if v.tool == CREATE_HOLD and a.attempts == 0:
        try:
            clash = slot_conflicts(code, v.args["start_ist"], v.args["end_ist"])
        except ToolCallError:
            clash = []  # the create call below will surface the outage
        if clash:
            return _fail(v, "permanent:precheck slot already busy", retryable=False)

    try:
        res = call_tool(v.tool, v.args)
    except ToolCallError as e:
        attempts = a.attempts + 1
        if e.retryable and attempts <= len(BACKOFF_S):
            row = state.update_action(
                v.id, status=ActionStatus.RETRYING, attempts_inc=1,
                next_attempt_at=now + timedelta(seconds=BACKOFF_S[attempts - 1]),
                result={"error": e.message[:300], "retryable": True}, actor="system",
            )  # fmt: skip
            state.audit("system", "action_retrying", v.id, {"attempt": attempts})
            return row
        state.update_action(v.id, attempts_inc=1, actor="system")
        return _fail(v, e.message, retryable=e.retryable)

    row = state.update_action(
        v.id, status=ActionStatus.EXECUTED, result=res, attempts_inc=1, actor="system"
    )
    state.audit("system", "action_executed", v.id, {"tool": v.tool, "code": code})
    _after_success(view(row))
    return row


def execute_ready(code: str | None = None, *, now: datetime | None = None) -> list[Action]:
    """Drain runnable actions (optionally for one code) in plan order until nothing changes."""
    changed: list[Action] = []
    for _ in range(50):
        progress = False
        views = actions_for(code) if code else all_views()
        for v in views:
            if v.status not in RUNNABLE:
                continue
            before = (v.status, v.action.attempts)
            row = execute(v.id, now=now)
            if (row.status, row.attempts) != before:
                changed.append(row)
                progress = True
        if not progress:
            break
    return changed


def run_due(now: datetime | None = None) -> list[Action]:
    """Outbox tick: retry every RETRYING action whose backoff has elapsed."""
    return execute_ready(None, now=now)
