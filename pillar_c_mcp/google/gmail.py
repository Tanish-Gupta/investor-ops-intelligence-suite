"""Gmail v1 wrapper (ported from M3): create — never send — the advisor email draft.

The recipient is fixed server-side (`ADVISOR_EMAIL`) and the body comes from the fixed
templates (with the Market Context block), so no caller can choose recipients or free text."""

from __future__ import annotations

import base64
from email.message import EmailMessage
from typing import Any

from ..templates import render


class GoogleGmail:
    def __init__(self, service: Any, advisor_email: str) -> None:
        self._svc = service
        self._to = advisor_email

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
        subject, body = render(
            template,
            code=code,
            topic=topic,
            slot=slot,
            call_summary=call_summary,
            market_context=market_context,
            pulse_id=pulse_id,
        )
        msg = EmailMessage()
        msg["To"] = self._to
        msg["Subject"] = subject
        msg.set_content(body)
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        draft = (
            self._svc.users().drafts().create(userId="me", body={"message": {"raw": raw}}).execute()
        )
        return {"draft_id": draft.get("id"), "subject": subject, "created": True}
