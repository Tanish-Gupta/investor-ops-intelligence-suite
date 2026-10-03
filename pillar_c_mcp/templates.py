"""Fixed advisor-email templates, rendered inside the FastMCP server (M3 `google_gmail.render`
extended with the Market Context block). Callers pass fields, never a free-form body."""

from __future__ import annotations

NO_PULSE_LINE = "Market Context: Not available this week."

_SUBJECTS = {
    "booking": "[Pre-booking] {code} — {topic} — {slot}",
    "reschedule": "[Rescheduled] {code} — {topic} — {slot}",
    "cancel": "[Cancelled] {code} — {topic} — {slot}",
    "waitlist": "[Waitlist] {code} — {topic} — {slot}",
    "ops_alert": "[Action needed] {code} — {topic}",
}

_INTROS = {
    "booking": "A tentative advisor call has been requested.",
    "reschedule": "A caller moved their tentative advisor call. The previous hold is released.",
    "cancel": "A caller cancelled their tentative advisor call. The calendar hold is released.",
    "waitlist": "No slot matched the caller's preference; they joined the waitlist.",
    "ops_alert": (
        "An automated step failed: the calendar hold could not be created after several "
        "retries. Please check the calendar and the Advisor Pre-Bookings notes manually."
    ),
}

_BODY = """Hi Advisor,

{intro}

• Booking code: {code}
• Topic: {topic}
• Slot: {slot} (tentative — please confirm)
• Caller: [REDACTED] (contact details will be shared via the secure link)
• Call summary: {call_summary}

📈 Customer sentiment before this meeting (Weekly Pulse {pulse_id}):
{market_context}

Reminder: provide factual information only; no investment advice on record.

— Investor Ops Suite (auto-drafted; approved in the HITL Approval Center)
"""


def render(
    template: str,
    *,
    code: str,
    topic: str,
    slot: str | None,
    call_summary: str | None = None,
    market_context: str | None = None,
    pulse_id: str | None = None,
) -> tuple[str, str]:
    if template not in _SUBJECTS:
        raise ValueError(f"unknown email template {template!r}")
    values = {
        "code": code,
        "topic": topic,
        "slot": slot or "n/a",
        "intro": _INTROS[template],
        "call_summary": (call_summary or "—").strip(),
        "market_context": (market_context or "").strip() or NO_PULSE_LINE,
        "pulse_id": pulse_id or "n/a",
    }
    return _SUBJECTS[template].format(**values), _BODY.format(**values)
