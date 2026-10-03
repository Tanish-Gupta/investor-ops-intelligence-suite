"""Google wrappers (ported from M3) against fake discovery services — no network, no credentials."""

from __future__ import annotations

import base64
import email
from email import policy

import pytest

from pillar_c_mcp.google import GoogleCalendar, GoogleDocs, GoogleGmail
from pillar_c_mcp.plan import hold_event_id


class HttpErr(Exception):
    def __init__(self, status: int) -> None:
        super().__init__(f"http {status}")
        self.resp = type("R", (), {"status": status})()


class Req:
    def __init__(self, fn):
        self.fn = fn

    def execute(self):
        return self.fn()


class FakeEvents:
    def __init__(self):
        self.store: dict[str, dict] = {}
        self.calls: list[str] = []

    def insert(self, calendarId, body):
        def go():
            self.calls.append("insert")
            if body["id"] in self.store:
                raise HttpErr(409)
            self.store[body["id"]] = {**body, "htmlLink": f"https://cal/{body['id']}"}
            return self.store[body["id"]]

        return Req(go)

    def get(self, calendarId, eventId):
        return Req(lambda: self.store[eventId])

    def update(self, calendarId, eventId, body):
        def go():
            self.calls.append("update")
            self.store[eventId] = {**body, "status": "tentative"}
            return self.store[eventId]

        return Req(go)

    def delete(self, calendarId, eventId, sendUpdates):
        def go():
            if eventId not in self.store or self.store[eventId]["status"] == "cancelled":
                raise HttpErr(410 if eventId in self.store else 404)
            self.store[eventId]["status"] = "cancelled"

        return Req(go)


class FakeCalendarSvc:
    def __init__(self, busy=None, errors=None):
        self._events = FakeEvents()
        self.busy = busy or []
        self.errors = errors

    def events(self):
        return self._events

    def freebusy(self):
        cal = {"busy": self.busy}
        if self.errors:
            cal["errors"] = self.errors
        return type(
            "F", (), {"query": lambda _s, body: Req(lambda: {"calendars": {"primary": cal}})}
        )()


ARGS = {
    "code": "NL-A123",
    "topic": "Nominee Updates",
    "kind": "booking",
    "version": 1,
    "start_ist": "2026-10-05T09:30:00+05:30",
    "end_ist": "2026-10-05T10:00:00+05:30",
}


def test_calendar_create_is_idempotent_and_revives_cancelled():
    svc = FakeCalendarSvc()
    cal = GoogleCalendar(svc)
    first = cal.create_hold(**ARGS)
    assert first["created"] and first["event_id"] == hold_event_id("NL-A123", "booking", 1)
    body = svc.events().store[first["event_id"]]
    assert body["status"] == "tentative" and "NL-A123" in body["summary"]
    again = cal.create_hold(**ARGS)  # 409 → existing event, not an error
    assert not again["created"] and again["event_id"] == first["event_id"]
    assert cal.delete_hold(first["event_id"]) is True
    assert cal.delete_hold(first["event_id"]) is True  # 410/404 → already gone
    revived = cal.create_hold(**ARGS)
    assert "update" in svc.events().calls and not revived["created"]
    assert svc.events().store[first["event_id"]]["status"] == "tentative"


def test_calendar_busy_and_errors():
    busy = [{"start": "2026-10-05T04:00:00Z", "end": "2026-10-05T04:30:00Z"}]
    assert (
        GoogleCalendar(FakeCalendarSvc(busy=busy)).list_busy(ARGS["start_ist"], ARGS["end_ist"])
        == busy
    )
    with pytest.raises(RuntimeError, match="notFound"):
        GoogleCalendar(FakeCalendarSvc(errors=[{"reason": "notFound"}])).list_busy(
            ARGS["start_ist"], ARGS["end_ist"]
        )

    class Boom(FakeEvents):
        def insert(self, calendarId, body):
            return Req(lambda: (_ for _ in ()).throw(HttpErr(503)))

    svc = FakeCalendarSvc()
    svc._events = Boom()
    with pytest.raises(HttpErr):
        GoogleCalendar(svc).create_hold(**ARGS)


class FakeDocsSvc:
    def __init__(self, text=""):
        self.text = text
        self.updates: list[dict] = []

    def documents(self):
        svc = self

        class D:
            def get(self, documentId):
                content = [
                    {
                        "paragraph": {"elements": [{"textRun": {"content": svc.text + "\n"}}]},
                        "endIndex": len(svc.text) + 2,
                    }
                ]
                return Req(lambda: {"body": {"content": content}})

            def batchUpdate(self, documentId, body):
                def go():
                    svc.updates.append(body)
                    svc.text += body["requests"][0]["insertText"]["text"]

                return Req(go)

        return D()


def test_docs_append_is_deduplicated():
    svc = FakeDocsSvc("Advisor Pre-Booking Notes")
    docs = GoogleDocs(svc, "doc-1")
    args = {
        "date": "2026-10-03",
        "topic": "Nominee Updates",
        "slot": "Mon, 5 Oct",
        "code": "NL-A123",
        "status": "tentative",
        "pulse_id": "PULSE-2026-W40",
    }
    first = docs.append_prebooking(**args)
    assert first["appended"] and first["line"].endswith("| PULSE-2026-W40")
    assert not docs.append_prebooking(**args)["appended"]
    assert len(svc.updates) == 1


def test_gmail_creates_draft_only():
    sent: list[dict] = []

    class Drafts:
        def create(self, userId, body):
            sent.append(body)
            return Req(lambda: {"id": "r-1"})

    class Users:
        def drafts(self):
            return Drafts()

        def messages(self):  # pragma: no cover - must never be used
            raise AssertionError("send path used")

    svc = type("G", (), {"users": lambda _s: Users()})()
    out = GoogleGmail(svc, "advisor@example.com").create_draft(
        template="booking",
        code="NL-A123",
        topic="Nominee Updates",
        slot="Mon, 5 Oct",
        market_context="Market Context (Pulse PULSE-2026-W40): top theme.",
        pulse_id="PULSE-2026-W40",
    )
    assert out["draft_id"] == "r-1" and "NL-A123" in out["subject"]
    raw = base64.urlsafe_b64decode(sent[0]["message"]["raw"])
    msg = email.message_from_bytes(raw, policy=policy.default)
    assert msg["To"] == "advisor@example.com" and "Market Context" in msg.get_content()
