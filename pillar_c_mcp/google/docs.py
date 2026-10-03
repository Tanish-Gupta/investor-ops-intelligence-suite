"""Google Docs v1 wrapper (ported from M3): append one line to the "Advisor Pre-Bookings" doc.

Line: `{date} | {topic} | {slot} | {code} | {status} | {pulse_id}`. Appends are deduplicated
against the current document text, so outbox retries never write twice."""

from __future__ import annotations

from typing import Any

from ..plan import prebooking_line


def _doc_text(doc: dict[str, Any]) -> str:
    parts: list[str] = []
    for el in (doc.get("body") or {}).get("content", []):
        for pe in (el.get("paragraph") or {}).get("elements", []):
            parts.append((pe.get("textRun") or {}).get("content", ""))
    return "".join(parts)


def _end_index(doc: dict[str, Any]) -> int:
    content = (doc.get("body") or {}).get("content", [])
    return int(content[-1].get("endIndex", 1)) if content else 1


class GoogleDocs:
    def __init__(self, service: Any, document_id: str) -> None:
        self._svc = service
        self._doc_id = document_id

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
        line = prebooking_line(date, topic, slot, code, status, pulse_id)
        doc = self._svc.documents().get(documentId=self._doc_id).execute()
        text = _doc_text(doc)
        if line in text.splitlines():
            return {"appended": False, "line": line, "doc": self._doc_id}
        index = max(1, _end_index(doc) - 1)  # the body always ends with a newline
        to_insert = line if text.strip() == "" else "\n" + line
        self._svc.documents().batchUpdate(
            documentId=self._doc_id,
            body={"requests": [{"insertText": {"location": {"index": index}, "text": to_insert}}]},
        ).execute()
        return {"appended": True, "line": line, "doc": self._doc_id}
