"""Rules-first NLU for the voice agent (ported from M3 nlu/rules.py) + opt-in LLM extraction."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from config.settings import get_settings
from core import guardrails, llm
from core.prompts import load_prompt

from . import booking, topics
from .when import Preference, parse_preference

_log = logging.getLogger(__name__)

IntentName = Literal[
    "BOOK_NEW", "RESCHEDULE", "CANCEL", "WHAT_TO_PREPARE", "CHECK_AVAILABILITY",
    "FAQ_QUESTION", "STOP", "HELP", "REPEAT", "SMALL_TALK", "UNKNOWN",
]  # fmt: skip
YesNo = Literal["yes", "no"]


def normalise(text: str) -> str:
    t = text.lower().replace("\u2019", "'").replace("\u2018", "'")
    t = re.sub(r"\b([ap])\.\s?m\b\.?", r"\1m", t)
    t = re.sub(r"(\d)\.(\d{2})\b", r"\1:\2", t)
    t = re.sub(r"[^a-z0-9\s:/'&-]", " ", t)
    t = re.sub(r"(?<![a-z0-9])-|-(?![a-z0-9])", " ", t)
    return re.sub(r"\s+", " ", t).strip()


_STOP = re.compile(
    r"(?:stop|bye|bye bye|goodbye|good bye|exit|quit|end|end call|end chat|that'?s all"
    r"|that is all|nothing else|no thanks|no thank you|no that'?s all|nope that'?s all"
    r"|thanks bye|thank you bye|no bye|no thats it|no that is it|that'?s it)(?: thanks| thank you)?"
)
_HELP = re.compile(r"(?:help|help me|menu|options|what can you do|what are (?:my|the) options)")
_REPEAT = re.compile(
    r"(?:(?:can|could) you |please )?(?:repeat(?: that| it)?|say (?:that |it )?again|pardon"
    r"|come again)(?: please)?"
)
_SMALL = re.compile(
    r"(?:hi|hello|hey|namaste|good (?:morning|afternoon|evening)|how are you|thanks|thank you"
    r"|who are you|are you a bot)(?: there)?"
)
_GREETING_PREFIX = re.compile(r"^(?:(?:hi|hello|hey|namaste)\b\s*(?:there\b\s*)?)?")

_YES = re.compile(
    r"^(?:y|k|ok|okay|yes|yea|yeah|ya|yup|yep|sure|alright|all right|fine|correct|right"
    r"|absolutely|definitely|of course|please do|do it|confirm|confirmed|go ahead|sounds good"
    r"|that works|works for me|perfect|great|proceed|book it|that'?s fine|that one|that"
    r"|haan|ha|ji)\b"
    r"|\b(?:go ahead|book it|confirm it|that works|sounds good|please proceed|that'?s right"
    r"|that'?s correct)\b"
)
_NO = re.compile(
    r"^(?:n|no(?! problem| worries| preference)|nope|nah|neither|none|not really|negative"
    r"|wrong|incorrect|nahi|not now|not today|not yet|no need)\b"
    r"|\b(?:neither|none of (?:them|these|those)|other (?:options?|slots?|times?)"
    r"|something else|different (?:time|day|slot|date)|another (?:time|day|slot|option|date)"
    r"|(?:doesn'?t|don'?t|won'?t|does not|do not) work|not convenient|can'?t make (?:it|that))\b"
)
_CANCEL = re.compile(
    r"\b(?:cancel\w*|call off|drop my (?:booking|appointment|slot)"
    r"|don'?t need the (?:appointment|slot|booking|call) anymore)\b"
)
_CANCEL_OBJECT = re.compile(
    r"\bcancel\w* (?:my |the |a |an )?(?:sip|sips|mandate|mandates|e-mandate|nach|autopay"
    r"|order|redemption|withdrawal|nomination|nominee|kyc)\b"
)
_BOOKING_NOUN = re.compile(r"\b(?:appointment|booking|slot|meeting|call|session|nl-?[a-z]\d)")
_RESCHEDULE = re.compile(
    r"\b(?:re-?schedul\w*|re-?book\w*|postpon\w*|prepon\w*)\b"
    r"|\b(?:move|shift|change|push|switch|modify)\b (?:my |the |our |this )?(?:existing |current "
    r"|booked )?(?:slot|time|timing|booking|appointment|meeting|call|date|session)\b"
)
_PREPARE = re.compile(
    r"\bwhat (?:do|should|shall|must|will) i (?:need to |have to )?(?:prepare|bring|keep ready"
    r"|have ready|carry|keep handy|need)\b|\b(?:prepare|preparation|checklist|keep ready)\b"
    r"|\bwhat (?:documents?|docs|papers)\b"
)
_AVAIL = re.compile(
    r"\b(?:availab\w*|free slots?|open slots?|what (?:slots|times|days|timings)"
    r"|which (?:slots|times|days)|any (?:slots|openings|free time)|openings)\b"
)
_EXPLICIT_BOOK = re.compile(r"\b(?:book\w*|reserve\w*|schedul\w*)\b")
_BOOK = re.compile(
    r"\b(?:book\w*|schedul\w*|appointment|consult\w*|talk to|speak (?:to|with)|meet|meeting"
    r"|call ?back|set up|arrange|reserve|an? advisor|the advisor|advisor call|session|discuss"
    r"|connect (?:me|with)|help (?:me )?with|need help|i want|i need|i'?d like)\b"
)
_FAQ = re.compile(
    r"^(?:what|how much|how many|is|are|does|do|can|which|when|why)\b.*\b(?:exit load|expense"
    r" ratio|ter|nav|lock-?in|minimum|min sip|benchmark|riskometer|stamp duty|stt|aum|fund"
    r"|scheme|elss|liquid|flexi ?cap|large ?cap|index)\b"
)
_SLOT_NUMBER = re.compile(r"\b(?:option|slot|number|no|choice|#)\s*(1|2|one|two)\b")
_SLOT_BARE = re.compile(r"(?:the )?(1|2|one|two)(?: please| works)?")
_SLOT_ORDINAL = re.compile(
    r"\b(?:the )?(first|second|1st|2nd|former|latter|earlier one|later one|last one)"
    r"(?! week| half)\b"
)
_SLOT_WORD = {"first": 1, "1st": 1, "former": 1, "earlier one": 1, "second": 2, "2nd": 2,
              "latter": 2, "later one": 2, "last one": 2, "1": 1, "one": 1, "2": 2,
              "two": 2}  # fmt: skip
_EARLIEST = re.compile(r"\b(?:earliest|first available|soonest|asap|next available)\b")


@dataclass
class NLUResult:
    intent: str = "UNKNOWN"
    topic: str | None = None
    topic_candidates: list[str] = field(default_factory=list)
    yes_no: str | None = None
    slot_choice: int | None = None
    booking_code: str | None = None
    pref: Preference = field(default_factory=Preference)
    source: str = "rules"

    @property
    def has_signal(self) -> bool:
        return bool(
            self.intent not in ("UNKNOWN",)
            or self.topic
            or self.topic_candidates
            or self.yes_no
            or self.slot_choice
            or self.booking_code
            or not self.pref.empty
        )


def yes_no(t: str) -> str | None:
    y, n = bool(_YES.search(t)), bool(_NO.search(t))
    if y and not n:
        return "yes"
    if n and not y:
        return "no"
    return None


def detect_intent(t: str) -> str:
    if _STOP.fullmatch(t):
        return "STOP"
    if _HELP.fullmatch(t):
        return "HELP"
    if _REPEAT.fullmatch(t):
        return "REPEAT"
    if _SMALL.fullmatch(t):
        return "SMALL_TALK"
    if _CANCEL.search(t) and not (_CANCEL_OBJECT.search(t) and not _BOOKING_NOUN.search(t)):
        return "CANCEL"
    if _RESCHEDULE.search(t):
        return "RESCHEDULE"
    if _PREPARE.search(t):
        return "WHAT_TO_PREPARE"
    if _AVAIL.search(t) and not _EXPLICIT_BOOK.search(t):
        return "CHECK_AVAILABILITY"
    if _FAQ.search(t) and not _EXPLICIT_BOOK.search(t):
        return "FAQ_QUESTION"
    if _BOOK.search(t):
        return "BOOK_NEW"
    return "UNKNOWN"


def slot_choice(t: str, offered_labels: list[str]) -> int | None:
    n = len(offered_labels)
    choice = None
    if m := _SLOT_NUMBER.search(t):
        choice = _SLOT_WORD[m.group(1)]
    elif m := _SLOT_BARE.fullmatch(t):
        choice = _SLOT_WORD[m.group(1)]
    elif m := _SLOT_ORDINAL.search(t):
        choice = n if m.group(1) in ("latter", "later one", "last one") else _SLOT_WORD[m.group(1)]
    elif _EARLIEST.search(t):
        choice = 1
    return choice if choice and 1 <= choice <= n else None


def parse(text: str, *, now: datetime, offered_labels: list[str] | None = None) -> NLUResult:
    t = normalise(text)
    body = _GREETING_PREFIX.sub("", t, count=1).strip() or t
    res = NLUResult(intent=detect_intent(body if body != t else t))
    if res.intent in ("STOP", "HELP", "REPEAT", "SMALL_TALK"):
        res.yes_no = yes_no(body)
        return res
    res.yes_no = yes_no(body)
    res.topic, cands = topics.match_topic(body)
    res.topic_candidates = cands if res.topic is None and len(cands) > 1 else []
    res.booking_code = booking.parse(text)
    res.pref = parse_preference(body, now)
    if offered_labels:
        res.slot_choice = slot_choice(body, offered_labels)
    return res


# --- opt-in LLM extraction ------------------------------------------------------------------
class LLMExtraction(BaseModel):
    intent: IntentName = "UNKNOWN"
    topic: Literal[topics.TOPIC_NAMES] | None = None  # type: ignore[valid-type]
    yes_no: YesNo | None = None
    slot_choice: int | None = Field(default=None, ge=1, le=2)
    day_text: str | None = Field(default=None, max_length=40)
    time_text: str | None = Field(default=None, max_length=40)


def llm_enabled(use_llm: bool | None = None) -> bool:
    on = get_settings().voice_llm_enabled if use_llm is None else use_llm
    return bool(on) and llm.llm_available()


def llm_parse(clean_text: str, state_name: str, *, now: datetime) -> NLUResult | None:
    """LLM fallback when rules found nothing. Input must already be PII-redacted."""
    try:
        out = llm.complete(
            load_prompt("voice_nlu.v1.md"),
            f"STATE: {state_name}\nUTTERANCE:\n<<<\n{clean_text}\n>>>",
            schema=LLMExtraction,
            model=get_settings().llm_voice_nlu,
            temperature=0.0,
            max_tokens=200,
        )
    except llm.LLMError as exc:
        _log.warning("voice_nlu_llm_failed", extra={"error": str(exc)[:200]})
        return None
    pref = parse_preference(" ".join(x for x in (out.day_text, out.time_text) if x), now)
    return NLUResult(
        intent=out.intent,
        topic=out.topic,
        yes_no=out.yes_no,
        slot_choice=out.slot_choice,
        pref=pref,
        source="llm",
    )


def guard(text: str) -> guardrails.GuardDecision:
    """Rules-only guard per turn (fast; short voice replies like 'Monday 3 pm' are allowed)."""
    return guardrails.check_input(text, use_llm=False)


def guard_blocks(d: guardrails.GuardDecision) -> bool:
    if d.intent in (guardrails.Intent.ADVICE, guardrails.Intent.PII_REQUEST):
        return True
    return d.intent is guardrails.Intent.OUT_OF_SCOPE and "prompt_injection" in d.reason
