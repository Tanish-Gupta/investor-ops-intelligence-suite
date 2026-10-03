"""Offline backends for `ADAPTER_MODE=mock`: same interface as the Google wrappers.

* LocalCalendar → `artifacts/holds/{code}-v{n}.ics` + `holds/index.json`; busy = the mock
  availability calendar's busy slots + live holds.
* LocalDocs     → the `## Bookings` section of `artifacts/notes.md` (via `core.notes`).
* LocalGmail    → `artifacts/drafts/{code}-{template}[-n].eml` (drafts only; nothing is sent).

Every backend counts its calls (`.calls`) so tests and evals can prove that nothing was
written while an action was still PENDING.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections import Counter
from datetime import UTC, datetime
from email.message import EmailMessage
from email.policy import SMTPUTF8
from pathlib import Path
from typing import Any

from config.settings import ROOT_DIR, get_settings
from core import notes

from ..plan import hold_event_id, hold_title, prebooking_line
from ..templates import render

AVAILABILITY_PATH = ROOT_DIR / "data" / "availability.json"


def _ics_time(iso: str) -> str:
    return datetime.fromisoformat(iso).strftime("%Y%m%dT%H%M%S")


def _overlaps(a_start: str, a_end: str, b_start: str, b_end: str) -> bool:
    return datetime.fromisoformat(a_start) < datetime.fromisoformat(b_end) and (
        datetime.fromisoformat(b_start) < datetime.fromisoformat(a_end)
    )


class LocalCalendar:
    def __init__(self, root: Path, availability_path: Path | None = None) -> None:
        self.dir = Path(root) / "holds"
        self.availability_path = Path(availability_path or AVAILABILITY_PATH)
        self.calls: Counter[str] = Counter()
        self._lock = threading.Lock()

    # --- index ------------------------------------------------------------------------------
    @property
    def _index_path(self) -> Path:
        return self.dir / "index.json"

    def _load(self) -> dict[str, dict[str, Any]]:
        p = self._index_path
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}

    def _save(self, index: dict[str, dict[str, Any]]) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self._index_path.write_text(json.dumps(index, indent=2, sort_keys=True), encoding="utf-8")

    def holds(self) -> list[dict[str, Any]]:
        return [{"event_id": k, **v} for k, v in self._load().items()]

    def _write_ics(self, event_id: str, ev: dict[str, Any]) -> Path:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        tz = get_settings().timezone
        body = "\r\n".join(
            [
                "BEGIN:VCALENDAR",
                "VERSION:2.0",
                "PRODID:-//Investor Ops Suite//Local Advisor Calendar//EN",
                "BEGIN:VEVENT",
                f"UID:{event_id}@investor-ops.local",
                f"DTSTAMP:{stamp}",
                f"DTSTART;TZID={tz}:{_ics_time(ev['start_ist'])}",
                f"DTEND;TZID={tz}:{_ics_time(ev['end_ist'])}",
                f"SUMMARY:{ev['title']}",
                f"DESCRIPTION:Tentative pre-booking {ev['code']} ({ev['topic']}). Contact "
                "details are collected separately via the secure link. Informational only\\, "
                "not investment advice.",
                f"STATUS:{'CANCELLED' if ev['status'] == 'cancelled' else 'TENTATIVE'}",
                f"TRANSP:{'TRANSPARENT' if ev['kind'] == 'waitlist' else 'OPAQUE'}",
                f"X-BOOKING-CODE:{ev['code']}",
                "END:VEVENT",
                "END:VCALENDAR",
                "",
            ]
        )
        path = self.dir / ev["file"]
        path.write_text(body, encoding="utf-8")
        return path

    # --- tool backends ---------------------------------------------------------------------
    def list_busy(self, start_ist: str, end_ist: str) -> list[dict[str, str]]:
        self.calls["list_busy"] += 1
        busy: list[dict[str, str]] = []
        if self.availability_path.exists():
            data = json.loads(self.availability_path.read_text(encoding="utf-8"))
            for day in data.get("days", []):
                for s in day.get("slots", []):
                    if s.get("status") == "busy" and _overlaps(
                        s["start"], s["end"], start_ist, end_ist
                    ):
                        busy.append({"start": s["start"], "end": s["end"]})
        for ev in self._load().values():
            if (
                ev["status"] != "cancelled"
                and ev["kind"] == "booking"
                and _overlaps(ev["start_ist"], ev["end_ist"], start_ist, end_ist)
            ):
                busy.append({"start": ev["start_ist"], "end": ev["end_ist"], "code": ev["code"]})
        return busy

    def create_hold(
        self, *, code: str, topic: str, start_ist: str, end_ist: str, kind: str, version: int
    ) -> dict[str, Any]:
        self.calls["create_hold"] += 1
        event_id = hold_event_id(code, kind, version)
        with self._lock:
            index = self._load()
            existing = index.get(event_id)
            created = existing is None
            suffix = "-waitlist" if kind == "waitlist" else ""
            ev = {
                "code": code,
                "topic": topic,
                "start_ist": start_ist,
                "end_ist": end_ist,
                "kind": kind,
                "version": version,
                "status": "tentative",
                "title": hold_title(topic, code, kind),
                "file": f"{code}{suffix}-v{version}.ics",
            }
            if existing and existing["status"] != "cancelled":
                ev = existing  # retry of an already created hold: no duplicate, no change
            index[event_id] = ev
            self._save(index)
            path = self._write_ics(event_id, ev)
        return {
            "event_id": event_id,
            "created": created,
            "html_link": path.resolve().as_uri(),
            "title": ev["title"],
        }

    def delete_hold(self, event_id: str) -> bool:
        """Mark the hold cancelled (kept on disk for audit). Unknown ids count as deleted."""
        self.calls["delete_hold"] += 1
        with self._lock:
            index = self._load()
            ev = index.get(event_id)
            if ev and ev["status"] != "cancelled":
                ev["status"] = "cancelled"
                self._save(index)
                self._write_ics(event_id, ev)
        return True


class LocalDocs:
    def __init__(self) -> None:
        self.calls: Counter[str] = Counter()

    def append_prebooking(
        self,
        *,
        date: str,
        topic: str,
        slot: str,
        code: str,
        status: str,
        pulse_id: str | None = None,
    ) -> dict[str, Any]:
        self.calls["append_prebooking"] += 1
        line = prebooking_line(date, topic, slot, code, status, pulse_id)
        if line in notes.booking_lines():  # outbox retries never write twice
            return {"appended": False, "line": line, "doc": str(notes.notes_path())}
        stored = notes.append_booking_line(line)
        return {"appended": True, "line": stored, "doc": str(notes.notes_path())}


class LocalGmail:
    def __init__(self, root: Path, advisor_email: str) -> None:
        self.dir = Path(root) / "drafts"
        self.to = advisor_email
        self.calls: Counter[str] = Counter()
        self._lock = threading.Lock()

    def create_draft(
        self,
        *,
        template: str,
        code: str,
        topic: str,
        slot: str | None = None,
        call_summary: str | None = None,
        market_context: str | None = None,
        pulse_id: str | None = None,
    ) -> dict[str, Any]:
        self.calls["create_draft"] += 1
        subject, body = render(
            template,
            code=code,
            topic=topic,
            slot=slot,
            call_summary=call_summary,
            market_context=market_context,
            pulse_id=pulse_id,
        )
        msg = EmailMessage(policy=SMTPUTF8)  # readable UTF-8 headers/body on disk
        msg["To"] = self.to
        msg["From"] = "investor-ops-suite@example.com"
        msg["Subject"] = subject
        msg["X-Booking-Code"] = code
        msg["X-Unsent"] = "1"  # opens as a draft in mail clients
        msg.set_content(body, cte="8bit")
        raw = msg.as_bytes()
        digest = hashlib.sha256(f"{subject}\n{body}".encode()).hexdigest()
        draft_id = "draft-" + digest[:12].translate(str.maketrans("0123456789", "ghijklmnop"))
        with self._lock:
            self.dir.mkdir(parents=True, exist_ok=True)
            n, created = 1, True
            while True:
                path = self.dir / f"{code}-{template}{'' if n == 1 else f'-{n}'}.eml"
                if not path.exists():
                    path.write_bytes(raw)
                    break
                id_file = path.with_suffix(".id")
                if id_file.exists() and id_file.read_text(encoding="utf-8") == draft_id:
                    created = False  # identical draft already exists (retry)
                    break
                n += 1
            path.with_suffix(".id").write_text(draft_id, encoding="utf-8")
        return {"draft_id": draft_id, "subject": subject, "created": created, "path": str(path)}
