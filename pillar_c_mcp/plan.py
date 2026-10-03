"""Tool plans (ported from M3 `domain/plan.py`): the exact MCP calls each booking outcome needs.

Pure data, no I/O. The HITL layer turns every write step into one PENDING action keyed
`{code}:{tool}:{tag}`; the ToolGate later checks that the executed args still equal the plan.

* BOOK        - create hold (v1) → notes line → advisor draft (M3 `BOOKING_WRITES`).
* RESCHEDULE  - same code, version + 1: create the new hold, release the old one, notes, draft.
* CANCEL      - release the hold, notes line, draft.
* COMPENSATE  - the hold finally failed: `hold_failed` notes line + `ops_alert` draft.
"""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from config.settings import get_settings

LIST_BUSY = "calendar_list_busy"
CREATE_HOLD = "calendar_create_hold"
DELETE_HOLD = "calendar_delete_hold"
DOCS_APPEND = "docs_append_prebooking"
GMAIL_DRAFT = "gmail_create_draft"

READ_TOOLS = frozenset({LIST_BUSY})
WRITE_TOOLS = frozenset({CREATE_HOLD, DELETE_HOLD, DOCS_APPEND, GMAIL_DRAFT})
ALL_TOOLS = READ_TOOLS | WRITE_TOOLS
BOOKING_WRITES = (CREATE_HOLD, DOCS_APPEND, GMAIL_DRAFT)

# Booking codes never use I or O (see pillar_b_voice.booking).
CODE_PATTERN = r"^NL-[A-HJ-NP-Z]\d{3}$"
IST_PATTERN = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?\+05:30$"
EVENT_ID_PATTERN = r"^[a-v0-9]{5,1024}$"
TEMPLATES = ("booking", "reschedule", "cancel", "waitlist", "ops_alert")
NOTE_STATUSES = ("tentative", "waitlist", "rescheduled", "cancelled", "hold_failed")
# The only args a reviewer may edit before approving (everything else is read-only).
EDITABLE_FIELDS = frozenset({"call_summary", "market_context"})
MAX_SUMMARY = 300
MAX_MARKET_CONTEXT = 600

_DIGIT_TO_LETTER = str.maketrans("0123456789", "abcdefghij")


def stable_id(text: str, n: int = 26) -> str:
    """Deterministic lowercase base32hex id with digits mapped to letters.

    Still a valid Google Calendar event id ([a-v0-9]); avoiding digit runs keeps the PII
    scrubber from mistaking an id for a phone or account number.
    """
    digest = hashlib.sha256(text.encode()).digest()
    raw = base64.b32hexencode(digest).decode().rstrip("=")[:n].lower()
    return raw.translate(_DIGIT_TO_LETTER)


def hold_event_id(code: str, kind: str = "booking", version: int = 1) -> str:
    """Deterministic event id per `{code}:{kind}:{version}` so a retried insert never duplicates."""
    return stable_id(f"{code}:{kind}:{version}")


def hold_title(topic: str, code: str, kind: str = "booking") -> str:
    if kind == "waitlist":
        return f"Advisor Q&A — Waitlist — {topic} — {code}"
    return f"Advisor Q&A — {topic} — {code}"


def prebooking_line(
    date_: str, topic: str, slot: str, code: str, status: str, pulse_id: str | None = None
) -> str:
    return f"{date_} | {topic} | {slot} | {code} | {status} | {pulse_id or 'no-pulse'}"


def ist_iso(dt: datetime) -> str:
    """'2026-10-06T15:00:00+05:30' — the only datetime format passed to the MCP tools."""
    return dt.astimezone(get_settings().tz).replace(microsecond=0).isoformat()


def slot_human(start: datetime) -> str:
    """'Tue, 6 Oct, 3:00 PM IST'."""
    s = start.astimezone(get_settings().tz)
    hour = s.strftime("%I:%M %p").lstrip("0")
    return f"{s:%a}, {s.day} {s:%b}, {hour} IST"


@dataclass(frozen=True)
class Step:
    tool: str
    args: dict[str, Any]


@dataclass(frozen=True)
class Plan:
    """One booking outcome → ordered write steps sharing an idempotency tag."""

    kind: str  # booking | reschedule | cancel | compensation
    code: str
    tag: str
    steps: tuple[Step, ...] = field(default_factory=tuple)


def _notes_args(
    *, booked_on: date, topic: str, slot: str, code: str, status: str, pulse_id: str | None
) -> dict[str, Any]:
    return {
        "date": booked_on.isoformat(),
        "topic": topic,
        "slot": slot,
        "code": code,
        "status": status,
        "pulse_id": pulse_id,
    }


def _draft_args(
    *,
    template: str,
    code: str,
    topic: str,
    slot: str,
    call_summary: str,
    market_context: str,
    pulse_id: str | None,
) -> dict[str, Any]:
    return {
        "template": template,
        "code": code,
        "topic": topic,
        "slot": slot,
        "call_summary": call_summary[:MAX_SUMMARY],
        "market_context": market_context[:MAX_MARKET_CONTEXT],
        "pulse_id": pulse_id,
    }


def booking_plan(
    *,
    code: str,
    topic: str,
    start: datetime,
    end: datetime,
    booked_on: date,
    call_summary: str,
    market_context: str,
    pulse_id: str | None,
) -> Plan:
    slot = slot_human(start)
    return Plan(
        "booking",
        code,
        "1",
        (
            Step(
                CREATE_HOLD,
                {
                    "code": code,
                    "topic": topic,
                    "start_ist": ist_iso(start),
                    "end_ist": ist_iso(end),
                    "kind": "booking",
                    "version": 1,
                },
            ),  # fmt: skip
            Step(
                DOCS_APPEND,
                _notes_args(
                    booked_on=booked_on,
                    topic=topic,
                    slot=slot,
                    code=code,
                    status="tentative",
                    pulse_id=pulse_id,
                ),
            ),  # fmt: skip
            Step(
                GMAIL_DRAFT,
                _draft_args(
                    template="booking",
                    code=code,
                    topic=topic,
                    slot=slot,
                    call_summary=call_summary,
                    market_context=market_context,
                    pulse_id=pulse_id,
                ),
            ),  # fmt: skip
        ),
    )


def reschedule_plan(
    *,
    code: str,
    topic: str,
    start: datetime,
    end: datetime,
    booked_on: date,
    version: int,
    previous_version: int,
    call_summary: str,
    market_context: str,
    pulse_id: str | None,
) -> Plan:
    """M3 order: create the new hold first, then release the old one (never leave no hold)."""
    slot = slot_human(start)
    return Plan(
        "reschedule",
        code,
        str(version),
        (
            Step(
                CREATE_HOLD,
                {
                    "code": code,
                    "topic": topic,
                    "start_ist": ist_iso(start),
                    "end_ist": ist_iso(end),
                    "kind": "booking",
                    "version": version,
                },
            ),  # fmt: skip
            Step(DELETE_HOLD, {"event_id": hold_event_id(code, "booking", previous_version)}),
            Step(
                DOCS_APPEND,
                _notes_args(
                    booked_on=booked_on,
                    topic=topic,
                    slot=slot,
                    code=code,
                    status="rescheduled",
                    pulse_id=pulse_id,
                ),
            ),  # fmt: skip
            Step(
                GMAIL_DRAFT,
                _draft_args(
                    template="reschedule",
                    code=code,
                    topic=topic,
                    slot=slot,
                    call_summary=call_summary,
                    market_context=market_context,
                    pulse_id=pulse_id,
                ),
            ),  # fmt: skip
        ),
    )


def cancel_plan(
    *,
    code: str,
    topic: str,
    start: datetime,
    booked_on: date,
    version: int,
    call_summary: str,
    market_context: str,
    pulse_id: str | None,
) -> Plan:
    slot = slot_human(start)
    return Plan(
        "cancel",
        code,
        "cancel",
        (
            Step(DELETE_HOLD, {"event_id": hold_event_id(code, "booking", version)}),
            Step(
                DOCS_APPEND,
                _notes_args(
                    booked_on=booked_on,
                    topic=topic,
                    slot=slot,
                    code=code,
                    status="cancelled",
                    pulse_id=pulse_id,
                ),
            ),  # fmt: skip
            Step(
                GMAIL_DRAFT,
                _draft_args(
                    template="cancel",
                    code=code,
                    topic=topic,
                    slot=slot,
                    call_summary=call_summary,
                    market_context=market_context,
                    pulse_id=pulse_id,
                ),
            ),  # fmt: skip
        ),
    )


def compensation_plan(
    *,
    code: str,
    topic: str,
    slot: str,
    booked_on: date,
    failed_tag: str,
    market_context: str,
    pulse_id: str | None,
) -> Plan:
    """M3 compensation: a dead `calendar_create_hold` → notes line + ops alert for a human."""
    summary = "The tentative calendar hold could not be created after retries."
    return Plan(
        "compensation",
        code,
        f"compensate-{failed_tag}",
        (
            Step(
                DOCS_APPEND,
                _notes_args(
                    booked_on=booked_on,
                    topic=topic,
                    slot=slot,
                    code=code,
                    status="hold_failed",
                    pulse_id=pulse_id,
                ),
            ),  # fmt: skip
            Step(
                GMAIL_DRAFT,
                _draft_args(
                    template="ops_alert",
                    code=code,
                    topic=topic,
                    slot=slot,
                    call_summary=summary,
                    market_context=market_context,
                    pulse_id=pulse_id,
                ),
            ),  # fmt: skip
        ),
    )
