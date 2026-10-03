"""Theme-aware booking agent (Pillar B): explicit dialog state machine, text-first.

`VoiceSession.start()` builds the greeting from the latest Weekly Pulse; `handle()` runs one turn;
`end()` writes `booking.json` and hands the result to Pillar C (`propose_for_booking`).
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

from config.settings import get_settings
from core import pii, state

from . import booking, nlu, topics
from .greeting import Greeting, build_greeting
from .slots import Slot, offer
from .when import Preference

_log = logging.getLogger(__name__)
MAX_FAILS = 3


class S(StrEnum):
    GREETING = "GREETING"
    INTENT = "INTENT"
    TOPIC = "TOPIC"
    TIME_PREF = "TIME_PREF"
    SLOT = "SLOT"
    CONFIRM = "CONFIRM"
    BOOKED = "BOOKED"
    WAITLIST = "WAITLIST"
    LOOKUP = "LOOKUP"
    CANCEL_CONFIRM = "CANCEL_CONFIRM"
    CANCELLED = "CANCELLED"
    PREPARE = "PREPARE"
    CLOSING = "CLOSING"


class AgentTurn(BaseModel):
    text: str
    speech: str = ""  # TTS form: booking codes spelled out
    audio_path: str | None = None
    state: str
    booking_code: str | None = None
    greeting_theme: str | None = None
    options: list[str] = Field(default_factory=list)
    refused: bool = False
    ended: bool = False


class BookingResult(BaseModel):
    booking_code: str
    action: Literal["BOOK", "RESCHEDULE", "CANCEL"]
    topic: str
    slot_start: datetime
    slot_end: datetime
    previous_slot_start: datetime | None = None
    previous_slot_end: datetime | None = None
    status: str
    pulse_id: str | None = None
    greeting_theme: str | None = None
    call_summary: str
    created_at: datetime

    @property
    def slot_label(self) -> str:
        return Slot(self.slot_start, self.slot_end).label()


Hook = Callable[[BookingResult], Any]
_CODE_IN_TEXT = re.compile(r"\bNL-[A-Z]\d{3}\b")


def default_hook(result: BookingResult) -> Any:
    """Phase 6 hand-off; a no-op until `pillar_c_mcp.actions` exists."""
    try:
        from pillar_c_mcp.actions import propose_for_booking
    except ImportError:
        return None
    return propose_for_booking(result)


def write_booking_json(result: BookingResult) -> str:
    folder = get_settings().artifacts_dir / "bookings"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{result.booking_code}.json"
    path.write_text(json.dumps(pii.scrub(result.model_dump(mode="json")), indent=2))
    return str(path)


class VoiceSession:
    def __init__(
        self,
        *,
        pulse: Any = "latest",
        now: Callable[[], datetime] | None = None,
        on_end: Hook | None = default_hook,
        faq_answer: Callable[[str], str | None] | None = None,
        use_llm: bool | None = None,
    ) -> None:
        self._pulse_arg = pulse
        self._now = now or state.now
        self.on_end = on_end
        self.faq_answer = faq_answer
        self.use_llm = use_llm
        self.state = S.GREETING
        self.greeting: Greeting | None = None
        self.transcript: list[tuple[str, str]] = []
        self.results: list[BookingResult] = []
        self.hook_outputs: list[Any] = []
        self.ended = False
        self._finalised = 0
        self._reset_flow()

    # --- lifecycle --------------------------------------------------------------------------
    def _reset_flow(self) -> None:
        self.mode: Literal["book", "reschedule", "cancel"] = "book"
        self.topic: str | None = None
        self.topic_options: list[str] = []
        self.pref = Preference()
        self.offered: list[Slot] = []
        self.seen: list[Slot] = []
        self.chosen: Slot | None = None
        self.target: state.Booking | None = None
        self.pending_topic: str | None = None
        self.fails: dict[str, int] = {}

    def start(self) -> AgentTurn:
        pulse = self._pulse_arg
        if pulse == "latest":
            from pillar_m2_pulse.pulse import get_latest_pulse

            pulse = get_latest_pulse()
        self.greeting = build_greeting(pulse, now=self._now())
        self.pending_topic = self.greeting.suggested_topic
        self.state = S.INTENT
        _log.info(
            "voice_start",
            extra={"kind": self.greeting.kind, "theme": self.greeting.theme,
                   "pulse_id": self.greeting.pulse_id},
        )  # fmt: skip
        opts = [self.pending_topic] if self.pending_topic else []
        return self._say(self.greeting.text, options=[*opts, "Book a call", "Reschedule", "Cancel"])

    def end(self) -> BookingResult | None:
        self.ended = True
        self.state = S.CLOSING
        for result in self.results[self._finalised :]:
            write_booking_json(result)
            if self.on_end is not None:
                try:
                    self.hook_outputs.append(self.on_end(result))
                except Exception:  # the booking itself is saved; surface but don't crash
                    _log.exception("voice_on_end_failed", extra={"code": result.booking_code})
        self._finalised = len(self.results)
        return self.results[-1] if self.results else None

    @property
    def greeting_theme(self) -> str | None:
        return self.greeting.theme if self.greeting else None

    # --- output helpers ---------------------------------------------------------------------
    def _say(
        self,
        text: str,
        *,
        options: list[str] | None = None,
        refused: bool = False,
        code: str | None = None,
    ) -> AgentTurn:
        self.transcript.append(("agent", text))
        self._last = text
        speech = _CODE_IN_TEXT.sub(lambda m: booking.spoken(m.group(0)), text)
        return AgentTurn(
            text=text,
            speech=speech,
            state=self.state.value,
            booking_code=code or (self.results[-1].booking_code if self.results else None),
            greeting_theme=self.greeting_theme,
            options=options or [],
            refused=refused,
            ended=self.ended,
        )

    def _finish(self, text: str) -> AgentTurn:
        self.end()
        return self._say(text)

    def _fail(self, text: str, options: list[str] | None = None) -> AgentTurn:
        n = self.fails.get(self.state.value, 0) + 1
        self.fails[self.state.value] = n
        if n >= MAX_FAILS:
            return self._finish(
                "Sorry, I'm having trouble understanding. Please try again from the app, or "
                "type your request. Goodbye!"
            )
        return self._say(text, options=options)

    # --- turn handling ----------------------------------------------------------------------
    def handle(self, user_text: str) -> AgentTurn:
        if self.state is S.GREETING:
            self.start()
        if self.ended:
            return self._say("This call has ended. Start a new call to continue.")
        decision = nlu.guard(user_text)
        clean = decision.clean_text
        self.transcript.append(("user", clean))
        if nlu.guard_blocks(decision):
            return self._say(decision.refusal or "", refused=True, options=self._reprompt_opts())

        now = self._now()
        r = nlu.parse(clean, now=now, offered_labels=[s.label() for s in self.offered])
        if not r.has_signal and nlu.llm_enabled(self.use_llm):
            r = nlu.llm_parse(clean, self.state.value, now=now) or r
        turn = self._dispatch(r, clean)
        if decision.notice:
            turn.text = f"{decision.notice} {turn.text}"
            turn.speech = f"{decision.notice} {turn.speech}"
            self.transcript[-1] = ("agent", turn.text)
            self._last = turn.text
        return turn

    def _reprompt_opts(self) -> list[str]:
        return ["Book a call", "What should I prepare?"]

    def _dispatch(self, r: nlu.NLUResult, clean: str) -> AgentTurn:
        if r.intent == "STOP" or (
            self.state in (S.BOOKED, S.CANCELLED) and r.yes_no == "no" and not r.topic
        ):
            return self._finish("Thank you for calling the Advisor Desk. Goodbye!")
        if r.intent == "HELP":
            return self._say(self._help_text())
        if r.intent == "REPEAT":
            return self._say(getattr(self, "_last", self.greeting.text if self.greeting else ""))
        handler = {
            S.INTENT: self._on_intent,
            S.BOOKED: self._on_intent,
            S.CANCELLED: self._on_intent,
            S.TOPIC: self._on_topic,
            S.PREPARE: self._on_prepare,
            S.TIME_PREF: self._on_time_pref,
            S.SLOT: self._on_slot,
            S.CONFIRM: self._on_confirm,
            S.LOOKUP: self._on_lookup,
            S.CANCEL_CONFIRM: self._on_cancel_confirm,
        }[self.state]
        return handler(r, clean)

    def _help_text(self) -> str:
        return (
            "I can book a new advisor call, reschedule or cancel one with your booking code, "
            f"check availability, or tell you what to prepare. Topics: {topics.spoken_list()}."
        )

    # --- INTENT -------------------------------------------------------------------------------
    def _on_intent(self, r: nlu.NLUResult, clean: str) -> AgentTurn:
        if self.state in (S.BOOKED, S.CANCELLED):
            self.state = S.INTENT
            self._reset_flow()
        if r.intent in ("CANCEL", "RESCHEDULE"):
            self.mode = "cancel" if r.intent == "CANCEL" else "reschedule"
            self.pref = r.pref
            if r.booking_code:
                return self._lookup(r.booking_code)
            self.state = S.LOOKUP
            return self._say("Sure. What's your booking code? It looks like NL-A742.")
        if r.intent == "WHAT_TO_PREPARE":
            topic = r.topic or self.topic or None
            if topic:
                return self._checklist(topic)
            self.state = S.PREPARE
            self.topic_options = list(topics.TOPIC_NAMES)
            return self._say(
                f"Happy to help. Which topic? {topics.numbered_list()}.",
                options=self.topic_options,
            )
        if r.intent == "FAQ_QUESTION":
            answer = self.faq_answer(clean) if self.faq_answer else None
            if answer:
                return self._say(f"{answer} Would you like to book an advisor call as well?")
            return self._say(
                "For fund facts and fees, please use the Unified Search tab — it gives cited "
                "answers from official sources. I can book an advisor call if you'd like."
            )
        if r.intent == "CHECK_AVAILABILITY":
            self.mode = "book"
            self.topic = r.topic or self.topic
            return self._offer(r.pref)

        topic = r.topic
        if not topic and r.yes_no == "yes" and self.pending_topic:
            topic = self.pending_topic
        bookish = r.intent == "BOOK_NEW" or topic or r.topic_candidates or not r.pref.empty
        if r.intent == "BOOK_NEW" and not topic and self.pending_topic and _refers_back(clean):
            topic = self.pending_topic
        if bookish or (r.yes_no == "yes"):
            self.mode = "book"
            if topic:
                self.topic = topic
                return self._after_topic(r.pref)
            return self._ask_topic(r.topic_candidates, r.pref)
        if r.yes_no == "no":
            return self._finish("No problem. Thank you for calling the Advisor Desk. Goodbye!")
        if r.intent == "SMALL_TALK":
            return self._say(f"Happy to help! {self._help_text()} What would you like to do?")
        return self._fail(
            "Sorry, I can only help with advisor calls here. "
            f"{self._help_text()} What would you like to do?",
            options=self._reprompt_opts(),
        )

    def _checklist(self, topic: str) -> AgentTurn:
        t = topics.get(topic)
        assert t is not None
        self.pending_topic = topic
        self.state = S.INTENT
        items = "; ".join(t.checklist)
        return self._say(
            f"For a {topic} call, please: {items}. Would you like to book a {topic} call?",
            options=["Yes, book it", "No, thanks"],
        )

    def _on_prepare(self, r: nlu.NLUResult, clean: str) -> AgentTurn:
        topic = topics.pick_from_list(nlu.normalise(clean), self.topic_options) or r.topic
        if topic:
            return self._checklist(topic)
        return self._fail(f"Which topic? {topics.numbered_list()}.", options=self.topic_options)

    # --- TOPIC --------------------------------------------------------------------------------
    def _ask_topic(self, candidates: list[str], pref: Preference) -> AgentTurn:
        if not pref.empty:
            self.pref = pref
        self.state = S.TOPIC
        self.topic_options = candidates or list(topics.TOPIC_NAMES)
        listing = "; ".join(f"{i}. {n}" for i, n in enumerate(self.topic_options, 1))
        lead = "That could be a few topics." if candidates else "Sure."
        return self._say(
            f"{lead} Which topic is the call about? {listing}.", options=self.topic_options
        )

    def _on_topic(self, r: nlu.NLUResult, clean: str) -> AgentTurn:
        topic = topics.pick_from_list(nlu.normalise(clean), self.topic_options) or r.topic
        if not topic and r.yes_no == "yes" and self.pending_topic:
            topic = self.pending_topic
        if not topic and r.topic_candidates:
            return self._ask_topic(r.topic_candidates, r.pref)
        if not topic:
            listing = "; ".join(f"{i}. {n}" for i, n in enumerate(self.topic_options, 1))
            return self._fail(f"Sorry, which topic? {listing}.", options=self.topic_options)
        self.topic = topic
        if self.chosen:
            return self._confirm_prompt()
        return self._after_topic(r.pref)

    def _after_topic(self, pref: Preference) -> AgentTurn:
        if not pref.empty:
            return self._offer(pref)
        if not self.pref.empty:
            return self._offer(self.pref)
        self.state = S.TIME_PREF
        return self._say(
            f"Great, a {self.topic} call. Which day and time suit you? For example, "
            "'tomorrow afternoon' or 'Monday 11 AM'. All times are IST.",
            options=["Earliest available", "Tomorrow morning", "Next week"],
        )

    # --- TIME / SLOTS ---------------------------------------------------------------------------
    def _on_time_pref(self, r: nlu.NLUResult, clean: str) -> AgentTurn:
        if not r.pref.empty or r.slot_choice or r.yes_no == "yes":
            pref = r.pref if not r.pref.empty else Preference(any=True)
            return self._offer(pref)
        return self._fail(
            "Which day and time works for you? You can say 'earliest available'.",
            options=["Earliest available", "Tomorrow morning"],
        )

    def _offer(self, pref: Preference, *, skip: list[Slot] | None = None) -> AgentTurn:
        self.pref = pref
        exclude = self.target.booking_code if self.target else None
        slots, exact = offer(pref, self._now(), skip=skip or [], exclude_code=exclude)
        if not slots:
            self.state = S.WAITLIST
            return self._finish(
                "Sorry, there are no advisor slots free in the next two weeks. Please try again "
                "in a few days from the app. Goodbye!"
            )
        self.offered = slots
        self.seen.extend(s for s in slots if s not in self.seen)
        self.state = S.SLOT
        lead = "" if exact or pref.empty or pref.any else f"I don't have {pref.describe()} free. "
        labels = [s.label() for s in slots]
        if len(slots) == 1:
            text = f"{lead}I have one slot: {labels[0]}. Shall I take it?"
        else:
            text = f"{lead}I have two options: 1. {labels[0]}, or 2. {labels[1]}. Which works?"
        return self._say(text, options=[*labels, "Other times"])

    def _on_slot(self, r: nlu.NLUResult, clean: str) -> AgentTurn:
        choice = r.slot_choice
        if choice is None and len(self.offered) == 1 and r.yes_no == "yes":
            choice = 1
        if choice is None:
            labels = [s.label().lower() for s in self.offered]
            norm = nlu.normalise(clean)
            hits = [i for i, lab in enumerate(labels) if norm and norm in lab]
            choice = hits[0] + 1 if len(hits) == 1 else None
        if choice:
            self.chosen = self.offered[choice - 1]
            if not self.topic:
                return self._ask_topic([], Preference())
            return self._confirm_prompt()
        if not r.pref.empty:
            return self._offer(r.pref)
        if r.yes_no == "no":
            return self._offer(Preference(any=True), skip=self.seen)
        return self._fail(
            "Please pick option 1 or 2, or tell me another day and time.",
            options=[s.label() for s in self.offered],
        )

    def _confirm_prompt(self) -> AgentTurn:
        assert self.chosen is not None
        self.state = S.CONFIRM
        if self.mode == "reschedule" and self.target:
            text = f"To confirm: move booking {self.target.booking_code} to {self.chosen.label()}?"
        else:
            text = f"To confirm: a tentative {self.topic} call on {self.chosen.label()}. Book it?"
        return self._say(text, options=["Yes", "No"])

    def _on_confirm(self, r: nlu.NLUResult, clean: str) -> AgentTurn:
        if r.yes_no == "yes":
            return self._commit()
        if r.yes_no == "no":
            skip = [*self.seen]
            self.chosen = None
            if not r.pref.empty:
                return self._offer(r.pref)
            return self._offer(Preference(any=True), skip=skip)
        if not r.pref.empty:
            self.chosen = None
            return self._offer(r.pref)
        return self._fail("Please say yes to confirm, or no to pick another time.", ["Yes", "No"])

    # --- commit -------------------------------------------------------------------------------
    def _pulse_id(self) -> str | None:
        pid = self.greeting.pulse_id if self.greeting else None
        return pid if pid and state.get_pulse(pid) else None

    def _summary(self, topic: str, action: str) -> str:
        theme = self.greeting_theme
        brief = f" The caller was greeted with this week's top theme, {theme}." if theme else ""
        verb = {"BOOK": "booked a tentative", "RESCHEDULE": "rescheduled their",
                "CANCEL": "cancelled their"}[action]  # fmt: skip
        return pii.redact(f"Caller {verb} {topic} advisor call by voice.{brief}")

    def _commit(self) -> AgentTurn:
        assert self.chosen is not None and self.topic is not None
        slot = self.chosen
        if self.mode == "reschedule" and self.target:
            code = self.target.booking_code
            row, old_start, old_end = state.reschedule_booking(code, slot.start, slot.end)
            result = BookingResult(
                booking_code=code,
                action="RESCHEDULE",
                topic=row.topic,
                slot_start=slot.start,
                slot_end=slot.end,
                previous_slot_start=old_start,
                previous_slot_end=old_end,
                status=row.status,
                pulse_id=self._pulse_id(),
                greeting_theme=self.greeting_theme,
                call_summary=self._summary(row.topic, "RESCHEDULE"),
                created_at=self._now(),
            )
            text = (
                f"Done. Booking {code} is moved to {slot.label()}. An advisor will confirm "
                "shortly. Anything else?"
            )
        else:
            code = booking.generate(lambda c: state.get_booking(c) is not None)
            row = state.create_booking(
                booking_code=code,
                topic=self.topic,
                slot_start=slot.start,
                slot_end=slot.end,
                pulse_id=self._pulse_id(),
                greeting_theme=self.greeting_theme,
            )
            result = BookingResult(
                booking_code=code,
                action="BOOK",
                topic=self.topic,
                slot_start=slot.start,
                slot_end=slot.end,
                status=row.status,
                pulse_id=row.pulse_id,
                greeting_theme=self.greeting_theme,
                call_summary=self._summary(self.topic, "BOOK"),
                created_at=self._now(),
            )
            text = (
                f"You're booked for a tentative {self.topic} call on {slot.label()}. Your "
                f"booking code is {code}. An advisor will confirm shortly. To share contact "
                "details securely, please use the link in the app with your booking code — "
                "don't share them on this call. Anything else?"
            )
        self.results.append(result)
        self.state = S.BOOKED
        return self._say(text, code=code, options=["No, that's all", "What should I prepare?"])

    # --- reschedule / cancel ------------------------------------------------------------------
    def _lookup(self, code: str) -> AgentTurn:
        row = state.get_booking(code)
        if row is None:
            return self._fail(f"I couldn't find booking {code}. Could you say the code again?")
        if row.status == state.BookingStatus.CANCELLED.value:
            self.state = S.INTENT
            return self._say(f"Booking {code} is already cancelled. Anything else?")
        self.target = row
        self.topic = row.topic
        tz = get_settings().tz
        current = Slot(row.slot_start_ist.astimezone(tz), row.slot_end_ist.astimezone(tz))
        if self.mode == "cancel":
            self.state = S.CANCEL_CONFIRM
            return self._say(
                f"I found your {row.topic} call on {current.label()}. Shall I cancel it?",
                options=["Yes, cancel", "No, keep it"],
            )
        if not self.pref.empty:
            return self._offer(self.pref)
        self.state = S.TIME_PREF
        return self._say(
            f"I found your {row.topic} call on {current.label()}. When would you like to move "
            "it to?",
            options=["Earliest available", "Tomorrow morning"],
        )

    def _on_lookup(self, r: nlu.NLUResult, clean: str) -> AgentTurn:
        if r.booking_code:
            if not r.pref.empty:
                self.pref = r.pref
            return self._lookup(r.booking_code)
        return self._fail("I need your booking code — it looks like N L dash A 7 4 2.")

    def _on_cancel_confirm(self, r: nlu.NLUResult, clean: str) -> AgentTurn:
        assert self.target is not None
        code = self.target.booking_code
        if r.yes_no == "yes":
            row = state.set_booking_status(code, state.BookingStatus.CANCELLED, actor="voice_agent")
            tz = get_settings().tz
            self.results.append(
                BookingResult(
                    booking_code=code,
                    action="CANCEL",
                    topic=row.topic,
                    slot_start=row.slot_start_ist.astimezone(tz),
                    slot_end=row.slot_end_ist.astimezone(tz),
                    status=row.status,
                    pulse_id=self._pulse_id(),
                    greeting_theme=self.greeting_theme,
                    call_summary=self._summary(row.topic, "CANCEL"),
                    created_at=self._now(),
                )
            )
            self.state = S.CANCELLED
            return self._say(
                f"Booking {code} is cancelled. The advisor's calendar hold will be released "
                "after review. Anything else?",
                code=code,
                options=["No, that's all", "Book a new call"],
            )
        if r.yes_no == "no":
            self.state = S.INTENT
            self._reset_flow()
            return self._say(f"Okay, booking {code} is kept. Anything else?")
        return self._fail("Please say yes to cancel, or no to keep the booking.", ["Yes", "No"])


_BACK_REF = re.compile(r"\b(?:that|this|it|same|the one you mentioned)\b")


def _refers_back(clean: str) -> bool:
    return bool(_BACK_REF.search(nlu.normalise(clean)))
