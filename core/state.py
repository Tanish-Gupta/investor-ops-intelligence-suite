"""Persistent state (docs/architecture.md §7): SQLite via SQLModel.

- WAL journal + foreign keys on every connection.
- All timestamps are timezone-aware and stored as ISO-8601 strings with offset; naive
  datetimes are rejected (rule E5/E9: never guess a timezone).
- JSON columns (`payload_json`, `result_json`, `details_json`, `themes_json`) are PII-scrubbed
  on write (rule P4), so nothing raw can reach disk through this module.
- `actions.idempotency_key` is UNIQUE (`{code}:{tool}:{version}`): `create_action` returns
  the existing row instead of duplicating (rule H4).
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import Column, String, UniqueConstraint, event
from sqlalchemy.engine import Engine
from sqlalchemy.types import TypeDecorator
from sqlmodel import Field, Session, SQLModel, create_engine, select

from config.settings import get_settings
from core import pii

BOOKING_CODE_RE = re.compile(r"^NL-[A-Z]\d{3}$")
PULSE_ID_RE = re.compile(r"^PULSE-\d{4}-W\d{2}$")


class BookingStatus(StrEnum):
    TENTATIVE = "TENTATIVE"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    RESCHEDULED = "RESCHEDULED"
    NEEDS_ATTENTION = "NEEDS_ATTENTION"  # Pillar C compensation: the calendar hold failed


class ActionStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    RETRYING = "RETRYING"
    REJECTED = "REJECTED"
    EXECUTED = "EXECUTED"
    FAILED = "FAILED"


class ActionTool(StrEnum):
    CALENDAR_CREATE_HOLD = "calendar_create_hold"
    CALENDAR_DELETE_HOLD = "calendar_delete_hold"
    DOCS_APPEND_PREBOOKING = "docs_append_prebooking"
    GMAIL_CREATE_DRAFT = "gmail_create_draft"


class StateError(ValueError):
    pass


class AwareDateTime(TypeDecorator):
    """Timezone-aware datetime stored as ISO-8601 text; rejects naive values."""

    impl = String(40)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> str | None:
        if value is None:
            return None
        if not isinstance(value, datetime):
            raise StateError(f"expected datetime, got {type(value).__name__}")
        if value.tzinfo is None or value.utcoffset() is None:
            raise StateError("naive datetime rejected; attach a timezone (e.g. Asia/Kolkata)")
        return value.isoformat()

    def process_result_value(self, value: str | None, dialect: Any) -> datetime | None:
        return datetime.fromisoformat(value) if value else None


def _ts() -> Any:
    return Field(default=None, sa_column=Column(AwareDateTime(), nullable=True))


def now() -> datetime:
    return datetime.now(get_settings().tz)


# --- Tables -------------------------------------------------------------------------------
class Pulse(SQLModel, table=True):
    __tablename__ = "pulses"
    pulse_id: str = Field(primary_key=True)
    week_start: date | None = None
    week_end: date | None = None
    review_count: int = 0
    top_theme: str | None = None
    themes_json: str = "[]"
    pulse_md: str = ""
    action_ideas: str = "[]"
    market_context: str = ""
    created_at: datetime | None = _ts()


class Booking(SQLModel, table=True):
    __tablename__ = "bookings"
    booking_code: str = Field(primary_key=True)
    topic: str
    slot_start_ist: datetime | None = _ts()
    slot_end_ist: datetime | None = _ts()
    status: str = BookingStatus.TENTATIVE.value
    pulse_id: str | None = Field(default=None, foreign_key="pulses.pulse_id")
    greeting_theme: str | None = None
    caller_label: str = pii.REDACTED
    created_at: datetime | None = _ts()


class Action(SQLModel, table=True):
    __tablename__ = "actions"
    action_id: str = Field(primary_key=True, default_factory=lambda: f"ACT-{uuid4().hex[:12]}")
    booking_code: str | None = Field(default=None, foreign_key="bookings.booking_code")
    tool: str
    payload_json: str = "{}"
    status: str = ActionStatus.PENDING.value
    idempotency_key: str = Field(sa_column_kwargs={"unique": True}, index=True)
    attempts: int = 0
    next_attempt_at: datetime | None = _ts()
    result_json: str | None = None
    reviewer: str | None = None
    decided_at: datetime | None = _ts()
    executed_at: datetime | None = _ts()


class AuditLog(SQLModel, table=True):
    __tablename__ = "audit_log"
    id: int | None = Field(default=None, primary_key=True)
    ts: datetime | None = _ts()
    actor: str
    event: str
    ref_id: str | None = None
    details_json: str = "{}"


class SchemeFact(SQLModel, table=True):
    __tablename__ = "scheme_facts"
    __table_args__ = (UniqueConstraint("scheme", "field", "source_doc_id"),)
    id: int | None = Field(default=None, primary_key=True)
    scheme: str
    field: str
    value: str | None = None
    unit: str | None = None
    conditions: str | None = None
    source_doc_id: str
    page: int | None = None
    url: str
    as_of: date | None = None
    verified_by_human: bool = False


# --- Engine -------------------------------------------------------------------------------
def _set_pragmas(dbapi_conn: Any, _record: Any) -> None:
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA busy_timeout=5000")
    cur.close()


@lru_cache(maxsize=8)
def get_engine(db_path: str | None = None) -> Engine:
    path = Path(db_path) if db_path else get_settings().db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    event.listen(engine, "connect", _set_pragmas)
    SQLModel.metadata.create_all(engine)
    return engine


@contextmanager
def session_scope(engine: Engine | None = None) -> Iterator[Session]:
    with Session(engine or get_engine(), expire_on_commit=False) as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise


def _dump(obj: Any) -> str:
    return json.dumps(pii.scrub(obj), ensure_ascii=False, default=str, sort_keys=True)


def loads(text: str | None) -> Any:
    return json.loads(text) if text else None


# --- Audit --------------------------------------------------------------------------------
def audit(
    actor: str,
    event_name: str,
    ref_id: str | None = None,
    details: dict[str, Any] | None = None,
    *,
    engine: Engine | None = None,
) -> AuditLog:
    row = AuditLog(
        ts=now(), actor=actor, event=event_name, ref_id=ref_id, details_json=_dump(details or {})
    )
    with session_scope(engine) as s:
        s.add(row)
    return row


def list_audit(ref_id: str | None = None, *, engine: Engine | None = None) -> list[AuditLog]:
    with session_scope(engine) as s:
        q = select(AuditLog).order_by(AuditLog.id)
        if ref_id:
            q = q.where(AuditLog.ref_id == ref_id)
        return list(s.exec(q))


# --- Pulses -------------------------------------------------------------------------------
def save_pulse(
    *,
    pulse_id: str,
    top_theme: str,
    themes: list[dict[str, Any]],
    pulse_md: str,
    action_ideas: list[str],
    market_context: str,
    review_count: int,
    week_start: date | None = None,
    week_end: date | None = None,
    engine: Engine | None = None,
) -> Pulse:
    if not PULSE_ID_RE.match(pulse_id):
        raise StateError(f"invalid pulse_id {pulse_id!r}")
    row = Pulse(
        pulse_id=pulse_id,
        week_start=week_start,
        week_end=week_end,
        review_count=review_count,
        top_theme=top_theme,
        themes_json=_dump(themes),
        pulse_md=pii.redact(pulse_md),
        action_ideas=_dump(action_ideas),
        market_context=pii.redact(market_context),
        created_at=now(),
    )
    with session_scope(engine) as s:
        s.merge(row)
    audit("system", "pulse_saved", pulse_id, {"top_theme": top_theme}, engine=engine)
    return row


def get_pulse(pulse_id: str, *, engine: Engine | None = None) -> Pulse | None:
    with session_scope(engine) as s:
        return s.get(Pulse, pulse_id)


def latest_pulse(*, engine: Engine | None = None) -> Pulse | None:
    with session_scope(engine) as s:
        return s.exec(select(Pulse).order_by(Pulse.created_at.desc())).first()  # type: ignore[union-attr]


# --- Bookings -----------------------------------------------------------------------------
def create_booking(
    *,
    booking_code: str,
    topic: str,
    slot_start: datetime,
    slot_end: datetime,
    pulse_id: str | None = None,
    greeting_theme: str | None = None,
    status: BookingStatus = BookingStatus.TENTATIVE,
    engine: Engine | None = None,
) -> Booking:
    if not BOOKING_CODE_RE.match(booking_code):
        raise StateError(f"invalid booking code {booking_code!r}")
    if slot_end <= slot_start:
        raise StateError("slot_end must be after slot_start")
    row = Booking(
        booking_code=booking_code,
        topic=topic,
        slot_start_ist=slot_start,
        slot_end_ist=slot_end,
        status=BookingStatus(status).value,
        pulse_id=pulse_id,
        greeting_theme=greeting_theme,
        created_at=now(),
    )
    with session_scope(engine) as s:
        if s.get(Booking, booking_code):
            raise StateError(f"booking {booking_code} already exists")
        s.add(row)
    audit("voice_agent", "booking_created", booking_code, {"topic": topic}, engine=engine)
    return row


def get_booking(code: str, *, engine: Engine | None = None) -> Booking | None:
    with session_scope(engine) as s:
        return s.get(Booking, code)


def list_bookings(*, engine: Engine | None = None) -> list[Booking]:
    with session_scope(engine) as s:
        return list(s.exec(select(Booking).order_by(Booking.created_at)))


def set_booking_status(
    code: str, status: BookingStatus, *, actor: str = "system", engine: Engine | None = None
) -> Booking:
    with session_scope(engine) as s:
        row = s.get(Booking, code)
        if row is None:
            raise StateError(f"unknown booking {code}")
        old = row.status
        row.status = BookingStatus(status).value
        s.add(row)
    audit(actor, "booking_status", code, {"from": old, "to": row.status}, engine=engine)
    return row


def reschedule_booking(
    code: str,
    slot_start: datetime,
    slot_end: datetime,
    *,
    actor: str = "voice_agent",
    engine: Engine | None = None,
) -> tuple[Booking, datetime | None, datetime | None]:
    """Move a booking to a new slot (status RESCHEDULED). Returns (row, old_start, old_end)."""
    if slot_end <= slot_start:
        raise StateError("slot_end must be after slot_start")
    with session_scope(engine) as s:
        row = s.get(Booking, code)
        if row is None:
            raise StateError(f"unknown booking {code}")
        if row.status == BookingStatus.CANCELLED.value:
            raise StateError(f"booking {code} is cancelled")
        old_start, old_end = row.slot_start_ist, row.slot_end_ist
        row.slot_start_ist, row.slot_end_ist = slot_start, slot_end
        row.status = BookingStatus.RESCHEDULED.value
        s.add(row)
    audit(
        actor,
        "booking_rescheduled",
        code,
        {"from": old_start.isoformat() if old_start else None, "to": slot_start.isoformat()},
        engine=engine,
    )
    return row, old_start, old_end


# --- Actions (HITL queue) -----------------------------------------------------------------
def idempotency_key(booking_code: str, tool: ActionTool | str, version: int | str = 1) -> str:
    return f"{booking_code}:{ActionTool(tool).value}:{version}"


def create_action(
    *,
    booking_code: str,
    tool: ActionTool | str,
    payload: dict[str, Any],
    version: int | str = 1,
    engine: Engine | None = None,
) -> tuple[Action, bool]:
    """Queue a PENDING action. Returns (action, created); an existing key is returned as-is."""
    key = idempotency_key(booking_code, tool, version)
    with session_scope(engine) as s:
        existing = s.exec(select(Action).where(Action.idempotency_key == key)).first()
        if existing:
            return existing, False
        row = Action(
            booking_code=booking_code,
            tool=ActionTool(tool).value,
            payload_json=_dump(payload),
            idempotency_key=key,
        )
        s.add(row)
    audit("system", "action_queued", row.action_id, {"key": key}, engine=engine)
    return row, True


def get_action(action_id: str, *, engine: Engine | None = None) -> Action | None:
    with session_scope(engine) as s:
        return s.get(Action, action_id)


def list_actions(
    status: ActionStatus | None = None,
    booking_code: str | None = None,
    *,
    engine: Engine | None = None,
) -> list[Action]:
    with session_scope(engine) as s:
        q = select(Action).order_by(Action.action_id)
        if status:
            q = q.where(Action.status == ActionStatus(status).value)
        if booking_code:
            q = q.where(Action.booking_code == booking_code)
        return list(s.exec(q))


def update_action(
    action_id: str,
    *,
    status: ActionStatus | None = None,
    payload: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
    reviewer: str | None = None,
    attempts_inc: int = 0,
    next_attempt_at: datetime | None = None,
    actor: str = "system",
    engine: Engine | None = None,
) -> Action:
    with session_scope(engine) as s:
        row = s.get(Action, action_id)
        if row is None:
            raise StateError(f"unknown action {action_id}")
        changes: dict[str, Any] = {}
        if payload is not None:
            row.payload_json = _dump(payload)
            changes["payload_edited"] = True
        if status is not None:
            changes["from"], row.status = row.status, ActionStatus(status).value
            changes["to"] = row.status
            if row.status in (ActionStatus.APPROVED, ActionStatus.REJECTED):
                row.decided_at = now()
            if row.status == ActionStatus.EXECUTED:
                row.executed_at = now()
        if result is not None:
            row.result_json = _dump(result)
        if reviewer is not None:
            row.reviewer = pii.redact(reviewer)
        row.attempts += attempts_inc
        row.next_attempt_at = next_attempt_at
        s.add(row)
    audit(actor, "action_updated", action_id, changes, engine=engine)
    return row


# --- Scheme facts (Pillar A) --------------------------------------------------------------
def upsert_scheme_fact(fact: SchemeFact, *, engine: Engine | None = None) -> SchemeFact:
    with session_scope(engine) as s:
        existing = s.exec(
            select(SchemeFact).where(
                SchemeFact.scheme == fact.scheme,
                SchemeFact.field == fact.field,
                SchemeFact.source_doc_id == fact.source_doc_id,
            )
        ).first()
        if existing:
            for k, v in fact.model_dump(exclude={"id"}).items():
                setattr(existing, k, v)
            s.add(existing)
            return existing
        s.add(fact)
        return fact


def get_scheme_facts(
    scheme: str | None = None, field: str | None = None, *, engine: Engine | None = None
) -> list[SchemeFact]:
    with session_scope(engine) as s:
        q = select(SchemeFact)
        if scheme:
            q = q.where(SchemeFact.scheme == scheme)
        if field:
            q = q.where(SchemeFact.field == field)
        return list(s.exec(q))
