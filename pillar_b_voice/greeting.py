"""Theme-aware greeting (Pillar B): deterministic templates driven by the latest Weekly Pulse."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Literal

from core import state
from pillar_m2_pulse.taxonomy import load_taxonomy

from . import topics

MAX_PULSE_AGE = timedelta(days=14)
WELCOME = "Hi, welcome to the Advisor Desk."
DISCLAIMER = (
    "Quick note: I share information only, not investment advice, and please don't share "
    "personal details like your phone number or PAN on this call."
)


@dataclass
class Greeting:
    text: str
    kind: Literal["bookable", "non_bookable", "generic"]
    theme: str | None
    pulse_id: str | None
    suggested_topic: str | None
    reason: str = ""


def _created(pulse: Any) -> datetime | None:
    raw = getattr(pulse, "created_at", None)
    if isinstance(raw, datetime):
        return raw
    if raw:
        try:
            return datetime.fromisoformat(str(raw))
        except ValueError:
            return None
    end = getattr(pulse, "week_end", None)
    if isinstance(end, date):
        return datetime.combine(end, datetime.min.time(), tzinfo=state.now().tzinfo)
    return None


def pulse_is_fresh(pulse: Any, now: datetime | None = None) -> bool:
    created = _created(pulse)
    if created is None:
        return False
    now = now or state.now()
    if created.tzinfo is None:
        created = created.replace(tzinfo=now.tzinfo)
    return now - created <= MAX_PULSE_AGE


def generic_text() -> str:
    return f"{WELCOME} I can help you book a call with an advisor for {topics.spoken_list()}."


def build_greeting(pulse: Any = None, *, now: datetime | None = None) -> Greeting:
    """`pulse` = latest `PulseResult` (or None). Stale (> 14 days) or theme-less → generic."""
    pid = getattr(pulse, "pulse_id", None)
    theme = getattr(pulse, "top_theme", None)
    if pulse is None or not theme:
        reason = "no_pulse" if pulse is None else "no_top_theme"
        return Greeting(f"{generic_text()} {DISCLAIMER}", "generic", None, pid, None, reason)
    if not pulse_is_fresh(pulse, now):
        return Greeting(f"{generic_text()} {DISCLAIMER}", "generic", None, pid, None, "stale")

    t = load_taxonomy().get(theme)
    voice_topic = t.voice_topic if t else None
    if voice_topic and topics.get(voice_topic):
        text = (
            f"{WELCOME} I see many users are asking about {theme} today — I can help you book "
            "a call for that! Or tell me what else you need."
        )
        return Greeting(f"{text} {DISCLAIMER}", "bookable", theme, pid, voice_topic, "fresh")
    text = (
        f"{WELCOME} I see many users are facing {theme} today — our support team is on it, and "
        "you can find help steps in the app's Help section. I can book an advisor call for "
        f"{topics.spoken_list()}."
    )
    return Greeting(f"{text} {DISCLAIMER}", "non_bookable", theme, pid, None, "fresh")
