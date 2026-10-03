"""Google Calendar v3 wrapper (ported from M3). The discovery `service` is injected, so tests
pass a fake. Event ids are deterministic per `{code}:{kind}:{version}`: a retried insert gets a
409 and is treated as success, so `calendar_create_hold` is idempotent at Google too."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ..plan import hold_event_id, hold_title

IST_TZ = "Asia/Kolkata"


def http_status(e: BaseException) -> int:
    """HTTP status of a googleapiclient `HttpError` (duck-typed: `e.resp.status`), else 0."""
    resp = getattr(e, "resp", None)
    return int(getattr(resp, "status", 0) or 0)


class GoogleCalendar:
    def __init__(self, service: Any, calendar_id: str = "primary") -> None:
        self._svc = service
        self._cal = calendar_id

    def list_busy(self, start_ist: str, end_ist: str) -> list[dict[str, str]]:
        body = {
            "timeMin": datetime.fromisoformat(start_ist).isoformat(),
            "timeMax": datetime.fromisoformat(end_ist).isoformat(),
            "timeZone": IST_TZ,
            "items": [{"id": self._cal}],
        }
        resp = self._svc.freebusy().query(body=body).execute()
        cal = (resp.get("calendars") or {}).get(self._cal) or {}
        if cal.get("errors"):
            reason = cal["errors"][0].get("reason", "unknown")
            raise RuntimeError(f"freebusy error for calendar: {reason}")
        return [{"start": b["start"], "end": b["end"]} for b in cal.get("busy", [])]

    def create_hold(
        self, *, code: str, topic: str, start_ist: str, end_ist: str, kind: str, version: int
    ) -> dict[str, Any]:
        event_id = hold_event_id(code, kind, version)
        body = {
            "id": event_id,
            "summary": hold_title(topic, code, kind),
            "description": (
                f"Tentative pre-booking {code} ({topic}). Created by the Investor Ops Suite after "
                "human approval. Contact details are collected separately via the secure link; "
                "informational only, not investment advice."
            ),
            "start": {"dateTime": start_ist, "timeZone": IST_TZ},
            "end": {"dateTime": end_ist, "timeZone": IST_TZ},
            "status": "tentative",
            "transparency": "transparent" if kind == "waitlist" else "opaque",
            "visibility": "private",
            "extendedProperties": {"private": {"booking_code": code, "kind": kind}},
        }
        try:
            ev = self._svc.events().insert(calendarId=self._cal, body=body).execute()
            return {
                "event_id": ev.get("id", event_id),
                "html_link": ev.get("htmlLink"),
                "created": True,
                "title": body["summary"],
            }
        except Exception as e:
            if http_status(e) != 409:
                raise
        # 409: the deterministic id exists (a retry). Revive it if it was deleted.
        ev = self._svc.events().get(calendarId=self._cal, eventId=event_id).execute()
        if ev.get("status") == "cancelled":
            ev = (
                self._svc.events()
                .update(calendarId=self._cal, eventId=event_id, body=body)
                .execute()
            )
        return {
            "event_id": event_id,
            "html_link": ev.get("htmlLink"),
            "created": False,
            "title": body["summary"],
        }

    def delete_hold(self, event_id: str) -> bool:
        try:
            self._svc.events().delete(
                calendarId=self._cal, eventId=event_id, sendUpdates="none"
            ).execute()
        except Exception as e:
            if http_status(e) in (404, 410):  # already gone: deletion is idempotent
                return True
            raise
        return True
