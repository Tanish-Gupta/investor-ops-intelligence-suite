from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from core import state
from core.pii import REDACTED

IST = ZoneInfo("Asia/Kolkata")
START = datetime(2026, 1, 14, 15, 0, tzinfo=IST)


@pytest.fixture
def engine(tmp_path):
    state.get_engine.cache_clear()
    eng = state.get_engine(str(tmp_path / "t.db"))
    yield eng
    state.get_engine.cache_clear()


def _pulse(engine):
    return state.save_pulse(
        pulse_id="PULSE-2026-W02",
        top_theme="Nominee Updates",
        themes=[{"name": "Nominee Updates", "count": 10}],
        pulse_md="Users (e.g. jane@example.com) struggle with nominee updates.",
        action_ideas=["a", "b", "c"],
        market_context="23% of reviews mention nominee updates.",
        review_count=40,
        week_start=date(2026, 1, 5),
        week_end=date(2026, 1, 11),
        engine=engine,
    )


def _booking(engine, code="NL-A742"):
    return state.create_booking(
        booking_code=code,
        topic="Nominee Updates",
        slot_start=START,
        slot_end=START + timedelta(minutes=30),
        pulse_id="PULSE-2026-W02",
        greeting_theme="Nominee Updates",
        engine=engine,
    )


def test_pragmas(engine):
    with engine.connect() as c:
        assert c.execute(text("PRAGMA journal_mode")).scalar() == "wal"
        assert c.execute(text("PRAGMA foreign_keys")).scalar() == 1


def test_pulse_roundtrip_scrubbed(engine):
    _pulse(engine)
    p = state.get_pulse("PULSE-2026-W02", engine=engine)
    assert p.top_theme == "Nominee Updates"
    assert "jane@example.com" not in p.pulse_md and REDACTED in p.pulse_md
    assert state.loads(p.action_ideas) == ["a", "b", "c"]
    assert p.created_at.tzinfo is not None
    assert state.latest_pulse(engine=engine).pulse_id == "PULSE-2026-W02"


def test_invalid_ids_rejected(engine):
    with pytest.raises(state.StateError):
        state.save_pulse(
            pulse_id="bad",
            top_theme="x",
            themes=[],
            pulse_md="",
            action_ideas=[],
            market_context="",
            review_count=0,
            engine=engine,
        )
    with pytest.raises(state.StateError):
        _booking(engine, code="AB-1234")


def test_booking_roundtrip_keeps_timezone(engine):
    _pulse(engine)
    _booking(engine)
    b = state.get_booking("NL-A742", engine=engine)
    assert b.slot_start_ist == START
    assert b.slot_start_ist.utcoffset() == timedelta(hours=5, minutes=30)
    assert b.caller_label == REDACTED and b.status == "TENTATIVE"
    state.set_booking_status("NL-A742", state.BookingStatus.CONFIRMED, engine=engine)
    assert state.get_booking("NL-A742", engine=engine).status == "CONFIRMED"


def test_naive_datetime_rejected(engine):
    with pytest.raises(Exception, match="naive"):
        state.create_booking(
            booking_code="NL-B234",
            topic="KYC",
            slot_start=datetime(2026, 1, 14, 15, 0),  # noqa: DTZ001 - deliberately naive
            slot_end=datetime(2026, 1, 14, 15, 30),  # noqa: DTZ001
            engine=engine,
        )


def test_duplicate_booking_rejected(engine):
    _pulse(engine)
    _booking(engine)
    with pytest.raises(state.StateError):
        _booking(engine)


def test_foreign_key_enforced(engine):
    with pytest.raises(Exception, match="FOREIGN KEY"):
        state.create_booking(
            booking_code="NL-C345",
            topic="KYC",
            slot_start=START,
            slot_end=START + timedelta(minutes=30),
            pulse_id="PULSE-1999-W01",
            engine=engine,
        )


def test_action_idempotency_and_scrub(engine):
    _pulse(engine)
    _booking(engine)
    payload = {"title": "Advisor call NL-A742", "note": "caller phone 9876543210"}
    a1, created1 = state.create_action(
        booking_code="NL-A742", tool="calendar_create_hold", payload=payload, engine=engine
    )
    a2, created2 = state.create_action(
        booking_code="NL-A742", tool="calendar_create_hold", payload=payload, engine=engine
    )
    assert created1 and not created2 and a1.action_id == a2.action_id
    assert a1.idempotency_key == "NL-A742:calendar_create_hold:1"
    stored = state.loads(state.get_action(a1.action_id, engine=engine).payload_json)
    assert "9876543210" not in str(stored) and "NL-A742" in stored["title"]
    assert len(state.list_actions(state.ActionStatus.PENDING, engine=engine)) == 1


def test_action_lifecycle_and_audit(engine):
    _pulse(engine)
    _booking(engine)
    a, _ = state.create_action(
        booking_code="NL-A742",
        tool="gmail_create_draft",
        payload={"to": "advisor@example.com"},
        engine=engine,
    )
    assert state.loads(a.payload_json)["to"] == "advisor@example.com"  # system address allowed
    state.update_action(
        a.action_id, status=state.ActionStatus.APPROVED, reviewer="ops", engine=engine
    )
    a = state.update_action(
        a.action_id,
        status=state.ActionStatus.EXECUTED,
        result={"draft_id": "d1"},
        attempts_inc=1,
        engine=engine,
    )
    assert a.decided_at and a.executed_at and a.attempts == 1
    events = [r.event for r in state.list_audit(engine=engine)]
    assert events.count("action_updated") == 2 and "booking_created" in events


def test_unknown_tool_rejected(engine):
    with pytest.raises(ValueError):
        state.create_action(booking_code="NL-A742", tool="send_email", payload={}, engine=engine)


def test_audit_details_scrubbed(engine):
    state.audit("user", "note", "x", {"msg": "my PAN is ABCPD1234E"}, engine=engine)
    row = state.list_audit("x", engine=engine)[0]
    assert "ABCPD1234E" not in row.details_json and row.ts.tzinfo is not None


def test_scheme_fact_upsert(engine):
    common = {
        "scheme": "Edelweiss ELSS Tax Saver Fund",
        "field": "lock_in",
        "value": "3",
        "unit": "years",
        "source_doc_id": "sid-1",
        "url": "https://example.com/sid",
    }
    state.upsert_scheme_fact(state.SchemeFact(**common), engine=engine)
    state.upsert_scheme_fact(state.SchemeFact(**common, conditions="from allotment"), engine=engine)
    rows = state.get_scheme_facts("Edelweiss ELSS Tax Saver Fund", engine=engine)
    assert len(rows) == 1 and rows[0].conditions == "from allotment"
