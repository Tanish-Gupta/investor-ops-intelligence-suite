"""Phase 6 contract tests: the FastMCP server exposes exactly the 5 allow-listed tools, validates
inputs, rejects PII/advice, is idempotent, and maps backend errors to retryable/permanent."""

from __future__ import annotations

import email
from email import policy

import pytest

from pillar_c_mcp import plan
from pillar_c_mcp.client import ToolCallError, ToolClient, UnexpectedToolError, run_sync
from pillar_c_mcp.local import LocalCalendar, LocalDocs, LocalGmail
from pillar_c_mcp.server import build_server

HOLD = {
    "code": "NL-A123",
    "topic": "Nominee Updates",
    "start_ist": "2026-10-05T09:30:00+05:30",
    "end_ist": "2026-10-05T10:00:00+05:30",
}


@pytest.fixture
def client(hitl):
    return ToolClient(hitl.server), hitl


def _call(c: ToolClient, tool: str, args: dict) -> dict:
    return run_sync(c.call(tool, args))


def test_exactly_five_tools_and_no_send(client):
    c, _ = client
    names = {d["name"] for d in run_sync(c.declarations())}
    assert names == set(plan.ALL_TOOLS) and len(names) == 5
    assert not any("send" in n for n in names)
    hold = next(d for d in run_sync(c.list_tools()) if d["name"] == plan.CREATE_HOLD)
    props = hold["parameters"]["properties"]
    assert props["code"]["pattern"] == plan.CODE_PATTERN and "enum" in str(props["topic"])


def test_unexpected_send_tool_fails_discovery(hitl):
    server = build_server(hitl.calendar, hitl.docs, hitl.gmail)

    @server.tool()
    async def gmail_send(code: str) -> dict:  # pragma: no cover - never called
        return {}

    with pytest.raises(UnexpectedToolError):
        run_sync(ToolClient(server).declarations())


def test_create_hold_is_idempotent_and_listed_busy(client):
    c, b = client
    first = _call(c, plan.CREATE_HOLD, HOLD)
    again = _call(c, plan.CREATE_HOLD, HOLD)
    assert first["created"] and not again["created"] and first["event_id"] == again["event_id"]
    assert "NL-A123" in first["title"] and len(b.calendar.holds()) == 1
    busy = _call(c, plan.LIST_BUSY, {"start_ist": HOLD["start_ist"], "end_ist": HOLD["end_ist"]})
    assert any(x.get("code") == "NL-A123" for x in busy["busy"])
    gone = _call(c, plan.DELETE_HOLD, {"event_id": first["event_id"]})
    assert gone["deleted"]
    busy = _call(c, plan.LIST_BUSY, {"start_ist": HOLD["start_ist"], "end_ist": HOLD["end_ist"]})
    assert not any(x.get("code") == "NL-A123" for x in busy["busy"])


@pytest.mark.parametrize(
    "bad",
    [
        {"code": "NL-I123"},
        {"code": "NL-12"},
        {"topic": "Crypto"},
        {"start_ist": "2026-10-05 09:30"},
        {"version": 0},
    ],
)
def test_schema_validation_is_permanent(client, bad):
    c, b = client
    with pytest.raises(ToolCallError) as e:
        _call(c, plan.CREATE_HOLD, {**HOLD, **bad})
    assert not e.value.retryable
    assert b.calendar.calls["create_hold"] == 0


def test_pii_and_advice_rejected_by_server(client):
    c, b = client
    base = {"template": "booking", "code": "NL-A123", "topic": "Nominee Updates"}
    with pytest.raises(ToolCallError, match="permanent:pii") as e:
        _call(c, plan.GMAIL_DRAFT, {**base, "call_summary": "call me on 9876543210"})
    assert not e.value.retryable
    with pytest.raises(ToolCallError, match="permanent:guardrail"):
        _call(c, plan.GMAIL_DRAFT, {**base, "call_summary": "You should invest in ELSS now"})
    assert b.gmail.calls["create_draft"] == 0


def test_draft_and_notes_carry_code_and_market_context(client):
    c, b = client
    mc = 'Market Context (Pulse PULSE-2026-W40): Top customer theme is "Nominee Updates".'
    res = _call(
        c,
        plan.GMAIL_DRAFT,
        {
            "template": "booking",
            "code": "NL-A123",
            "topic": "Nominee Updates",
            "slot": "Mon, 5 Oct",
            "market_context": mc,
            "pulse_id": "PULSE-2026-W40",
        },
    )
    msg = email.message_from_bytes(open(res["path"], "rb").read(), policy=policy.default)
    assert "NL-A123" in msg["Subject"]
    body = msg.get_content()
    assert "Market Context" in body and "PULSE-2026-W40" in body and "[REDACTED]" in body
    again = _call(
        c,
        plan.GMAIL_DRAFT,
        {
            "template": "booking",
            "code": "NL-A123",
            "topic": "Nominee Updates",
            "slot": "Mon, 5 Oct",
            "market_context": mc,
            "pulse_id": "PULSE-2026-W40",
        },
    )
    assert not again["created"] and again["draft_id"] == res["draft_id"]

    args = {
        "date": "2026-10-03",
        "topic": "Nominee Updates",
        "slot": "Mon, 5 Oct",
        "code": "NL-A123",
        "status": "tentative",
        "pulse_id": "PULSE-2026-W40",
    }
    first = _call(c, plan.DOCS_APPEND, args)
    second = _call(c, plan.DOCS_APPEND, args)
    assert first["appended"] and not second["appended"]
    assert first["line"].endswith("| NL-A123 | tentative | PULSE-2026-W40")


class _HttpErr(Exception):
    def __init__(self, status: int) -> None:
        super().__init__(f"http {status}")
        self.resp = type("R", (), {"status": status})()


class _Boom(LocalCalendar):
    def __init__(self, root, exc):
        super().__init__(root)
        self.exc = exc

    def create_hold(self, **kw):
        raise self.exc


@pytest.mark.parametrize(
    ("exc", "retryable"),
    [
        (_HttpErr(503), True),
        (_HttpErr(429), True),
        (_HttpErr(400), False),
        (_HttpErr(403), False),
        (OSError("net down"), True),
        (TimeoutError(), True),
        (ValueError("bad"), False),
    ],
)
def test_backend_error_mapping(workspace, exc, retryable):
    server = build_server(_Boom(workspace, exc), LocalDocs(), LocalGmail(workspace, "a@b.example"))
    with pytest.raises(ToolCallError) as e:
        _call(ToolClient(server), plan.CREATE_HOLD, HOLD)
    assert e.value.retryable is retryable
    assert ("retryable:" if retryable else "permanent:") in e.value.message


def test_plan_helpers():
    assert plan.hold_event_id("NL-A123", "booking", 1) == plan.hold_event_id(
        "NL-A123", "booking", 1
    )
    assert plan.hold_event_id("NL-A123", "booking", 1) != plan.hold_event_id(
        "NL-A123", "booking", 2
    )
    eid = plan.hold_event_id("NL-A123", "booking", 1)
    import re

    assert re.fullmatch(plan.EVENT_ID_PATTERN, eid)
    line = plan.prebooking_line(
        "2026-10-03", "Nominee Updates", "Mon", "NL-A123", "tentative", None
    )
    assert line.endswith("| no-pulse")
