"""Compliance guardrails (docs/rules.md C1–C7, P1–P7, §9) shared by every pillar.

Input:  `check_input(text)` → `GuardDecision`
    1. PII scan on the raw text → `PII_SHARED` flag; everything downstream sees the redacted text.
    2. Deterministic rules (M3 advice patterns + M1 markers + capstone additions, PII-request,
       prompt-injection, empty/gibberish) — fast, offline, and the source of truth for evals.
    3. Only when no blocking rule fires: LLM intent classifier (Pydantic, temperature 0) to catch
       subtle advice / off-topic requests. If the LLM is disabled or unavailable, a domain-keyword
       fallback decides ALLOWED vs OUT_OF_SCOPE.
    Primary intent priority: PII_REQUEST > ADVICE > OUT_OF_SCOPE > ALLOWED. `PII_SHARED` alone
    never blocks: the text is masked and a reminder is attached (`notice`).

Output: `check_output(text)` → `OutputCheck` — last line of defence on every generated
    message (advice phrasing, PII). On violation the caller shows `safe_text` (safe fallback).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

from config.settings import get_settings
from core import pii
from core.prompts import load_prompt, load_yaml, refusal

_log = logging.getLogger(__name__)


class Intent(StrEnum):
    ALLOWED = "ALLOWED"
    ADVICE = "ADVICE"
    PII_REQUEST = "PII_REQUEST"
    PII_SHARED = "PII_SHARED"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"


BLOCKING = frozenset({Intent.ADVICE, Intent.PII_REQUEST, Intent.OUT_OF_SCOPE})
_PRIORITY = (Intent.PII_REQUEST, Intent.ADVICE, Intent.OUT_OF_SCOPE)

# --- Advice rules -------------------------------------------------------------------------
# Ported from M3 guardrails/advice.py (stage-1 rules) …
_M3_ADVICE = (
    r"\bshould (?:i|we) (?:buy|sell|invest|redeem|switch|hold|stop my|start|exit|put"
    r"|move my money|book profit|be investing)",
    r"\b(?:recommend|suggest)\w*\b[a-z0-9 ']{0,30}\b(?:funds?|stocks?|shares?|schemes?"
    r"|portfolio|gold|crypto|bitcoin|equity|investments?|ipos?|nfos?|elss|sips?)\b",
    r"\b(?:which|what) (?:mutual )?(?:funds?|stocks?|shares?|schemes?|sips?|ipos?|nfos?"
    r"|investments?|elss) (?:should|to|would|will|can|do)\b",
    r"\b(?:best|top|good|better|safest|safe|high[- ]return)\b(?: [a-z]+){0,2}"
    r" (?:funds?|stocks?|shares?|schemes?|investments?|ipos?|portfolio|elss|sips?(?! dates?))\b",
    r"\b(?:investment|financial|stock|share|trading|tax[- ]saving|portfolio)"
    r" (?:advice|tips?|recommendations?|suggestions?|ideas?)\b",
    r"\b(?:where|what|how much|how) (?:should|can|do) i invest\b",
    r"\bis (?:it|this|now) (?:a )?(?:good|right|bad|the right) time to"
    r" (?:buy|sell|invest|redeem|exit|enter)\b",
    r"\b(?:will|would|is) (?:the )?(?:market|nifty|sensex|stock|price|nav)s?"
    r" (?:go|rise|fall|crash|recover|going)\b",
    r"\b(?:guaranteed|expected|best|highest|good|better|maximum) returns?\b",
    r"\bbuy or sell\b|\bsell or (?:buy|hold)\b|\bhold or sell\b|\bstock tips?\b|\bmultibagger\b",
    r"\b(?:returns?|navs?) (?:will|would|is going to|are going to)\b",
    r"\bis (?:[a-z]+ ){1,4}(?:a )?(?:good|safe|bad|risky) (?:investment|to invest|bet)\b",
)
# … M1 routing.py advice markers …
_M1_ADVICE = (
    r"\bwhat to buy\b|\bgood investment\b|\bbeat the market\b|\bworth (?:it|buying|selling"
    r"|investing)\b|\bopinion on\b|\bwhat do you think (?:about|of)\b",
    r"\b(?:my|your) portfolio\b|\b(?:build|rebalance|diversify) (?:a |my )?portfolio\b"
    r"|\bportfolio (?:advice|construction)\b",
    r"\b(?:better|worth it) to (?:buy|sell|invest|redeem|switch)\b",
    r"\bwhere should i put my money\b",
)
# … and capstone additions (evals S1, S3, S5, S7 and paraphrases).
_CAPSTONE_ADVICE = (
    r"\bwill (?:give|return|fetch|earn|generate|double|make)\b[^.?!]{0,40}\d+ ?%",
    r"\b(?:give|get|earn|make) (?:me )?\d+ ?%(?: returns?)?\b",
    r"\b\d+ ?% (?:returns?|cagr|gains?|profit)\b[^.?!]{0,30}\b(?:which|what|how|will|can)\b"
    r"|\b(?:which|what)\b[^.?!]{0,40}\b\d+ ?% (?:returns?|cagr|gains?|profit)\b",
    r"\bwhich\b(?: [a-z]+){0,4} should (?:i|we)\b",
    r"\bwhich (?:one |fund |scheme |option )?(?:is|would be|will be) (?:better|best|safer"
    r"|the best|more profitable)\b",
    r"\bcompare\b[^.?!]{0,80}\b(?:which|better|best|recommend|choose|pick)\b",
    r"\b(?:better|best) (?:between|among|out of)\b|\b(?:vs|versus)\b[^.?!]{0,40}\bbetter\b",
    r"\b(?:redeem|sell|buy|invest|switch|exit|stop)\b[^.?!]{0,40}\b(?:now|today)\b"
    r"[^.?!]{0,20}\bor (?:wait|later|hold|after)\b",
    r"\b(?:suitable|right|ideal) (?:fund |scheme )?for me\b|\bfor my (?:goals?|risk)\b",
    r"\bsave the most tax\b|\bmaximi[sz]e (?:my )?(?:returns?|gains?|tax saving)\b",
    r"\b(?:allocate|allocation of) my\b|\bhow much should i (?:put|invest|allocate)\b",
)
ADVICE_RULES: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p) for p in (*_M3_ADVICE, *_M1_ADVICE, *_CAPSTONE_ADVICE)
)

_INJECTION = re.compile(
    r"\b(?:ignore|disregard|forget|override|bypass) (?:all |any |the |your |these |my )*"
    r"(?:previous|prior|above|earlier|system|safety|compliance)? ?(?:instructions?|rules|"
    r"prompts?|guardrails|guidelines|constraints)\b"
    r"|\b(?:you are now|act as|pretend (?:to be|you are)|developer mode|jailbreak|dan mode)\b"
    r"|\b(?:reveal|show|print) (?:your |the )?(?:system prompt|instructions)\b"
)

# --- PII-request rules ------------------------------------------------------------------
_CONTACT = (
    r"(?:e-?mail(?: id| address)?|mail id|phone(?: number| no)?|mobile(?: number| no)?"
    r"|contact(?: details| number| info)?|whatsapp|(?:home |office )?address|linkedin"
    r"|personal number|cell(?: number)?|pan(?: number)?|aadhaa?r|account number|salary)"
)
_PERSON_ROLE = (
    r"(?:ceo|cfo|cto|coo|founders?|co-?founders?|chairman|chairperson|md|managing director"
    r"|directors?|president|vp|employees?|staff|advisors?|advisers?|agents?|executives?|rm"
    r"|relationship managers?|fund managers?|managers?|owner|boss"
    r"|another (?:user|customer|investor)|other (?:users|customers|investors)"
    r"|someone|somebody|this person|that person|him|her"
    r"|[a-z]+ (?:sharma|kumar|singh|gupta|jain|patel|iyer|rao|reddy|shah|mehta|nair))"
)
PII_REQUEST_RULES: tuple[re.Pattern[str], ...] = (
    re.compile(rf"\b{_PERSON_ROLE}(?:'s|s')?(?: [a-z]+){{0,3}} {_CONTACT}\b"),
    re.compile(rf"\b{_CONTACT}(?: [a-z']+){{0,6}} (?:of|for|from) (?:the |my |your |our |a |an )?"
               rf"(?:[a-z']+ ){{0,3}}{_PERSON_ROLE}\b"),
    re.compile(r"\b(?:his|her|their) (?:e-?mail|phone|mobile|number|address|contact)\b"),
    # A redacted person name: "[REDACTED]'s phone" / "email of [REDACTED]".
    re.compile(rf"\bredacted ?'s(?: [a-z]+){{0,2}} {_CONTACT}\b"),
    re.compile(rf"\b{_CONTACT} (?:of|for) redacted\b"),
    re.compile(r"\b(?:who is|details of|dox|find) (?:the )?(?:customers?|users?|investors?)"
               r" (?:who|that|with)\b"),
)  # fmt: skip

# --- Scope / fallback ---------------------------------------------------------------------
_DOMAIN = re.compile(
    r"\b(?:funds?|mf|mutual|schemes?|nav|exit load|load|expense ratio|ter|lock-?in|elss|sip|swp"
    r"|stp|kyc|nominee|fees?|charges?|charged|stamp duty|stt|tax|capital gains?|redeem"
    r"|redemption|withdraw\w*|units?|folio|statement|benchmark|riskometer|aum|factsheet|amc"
    r"|edelweiss|groww|indmoney|flexi ?cap|fof|book\w*|appointment|call|advisor|adviser|slot"
    r"|reschedul\w*|cancel\w*|meeting|login|log in|otp|app|account|kyc|mandate|autopay|upi"
    r"|refund|dividend|idcw|growth|direct plan|regular plan|minimum|investment|invest\w*"
    r"|customer care|support|helpline|complaint|grievance|nl-?[a-z]\d{3}"
    r"|hi|hello|hey|namaste|thanks|thank you|yes|no|ok|okay|help)\b"
)
_LETTERS = re.compile(r"[a-z]")


class IntentClassification(BaseModel):
    """Structured output of the LLM intent classifier."""

    intent: Literal["ALLOWED", "ADVICE", "PII_REQUEST", "OUT_OF_SCOPE"]
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(default="", max_length=300)


@dataclass
class GuardDecision:
    intent: Intent
    flags: frozenset[Intent]
    clean_text: str  # PII-redacted input; the only version that may flow downstream
    pii_types: list[str] = field(default_factory=list)
    source: Literal["rule", "llm", "fallback"] = "rule"
    reason: str = ""
    refusal: str | None = None  # full user-facing response when blocked
    notice: str | None = None  # PII reminder to prepend to an allowed answer
    links: list[str] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return self.intent in BLOCKING

    @property
    def pii_shared(self) -> bool:
        return Intent.PII_SHARED in self.flags


@dataclass
class OutputCheck:
    ok: bool
    violations: list[str]
    safe_text: str


def normalise(text: str) -> str:
    t = text.lower().replace("\u2019", "'").replace("\u2018", "'")
    t = re.sub(r"[^a-z0-9\s%:/'&.?!,-]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _is_gibberish(norm: str) -> bool:
    letters = _LETTERS.findall(norm)
    if len(letters) < 2:
        return True
    words = re.findall(r"[a-z]+", norm)
    if words and all(not re.search(r"[aeiouy]", w) for w in words if len(w) > 3):
        return len([w for w in words if len(w) > 3]) > 0 and not _DOMAIN.search(norm)
    return False


def _first_match(rules: tuple[re.Pattern[str], ...], norm: str) -> int | None:
    for i, rule in enumerate(rules):
        if rule.search(norm):
            return i
    return None


def _rule_flags(norm: str) -> tuple[set[Intent], list[str]]:
    flags: set[Intent] = set()
    reasons: list[str] = []
    if not norm or _is_gibberish(norm):
        return {Intent.OUT_OF_SCOPE}, ["empty_or_gibberish"]
    if (i := _first_match(PII_REQUEST_RULES, norm)) is not None:
        flags.add(Intent.PII_REQUEST)
        reasons.append(f"pii_request_rule:{i}")
    if (i := _first_match(ADVICE_RULES, norm)) is not None:
        flags.add(Intent.ADVICE)
        reasons.append(f"advice_rule:{i}")
    if _INJECTION.search(norm):
        reasons.append("prompt_injection")
        if not flags:  # injection without another blocking intent → refuse as out of scope
            flags.add(Intent.OUT_OF_SCOPE)
    return flags, reasons


def _llm_classify(clean_text: str) -> IntentClassification | None:
    from core.llm import LLMError, complete, llm_available

    if not llm_available():
        return None
    try:
        return complete(
            load_prompt("guardrail_classifier.v1.md"),
            f"USER MESSAGE:\n<<<\n{clean_text}\n>>>",
            schema=IntentClassification,
            temperature=0.0,
            max_tokens=200,
        )
    except LLMError as exc:
        _log.warning("guard_llm_failed", extra={"error": str(exc)[:200]})
        return None


def _compose(decision: GuardDecision) -> GuardDecision:
    reminder = refusal("pii_shared") if decision.pii_shared else None
    if decision.blocked:
        kind = {
            Intent.ADVICE: "advice",
            Intent.PII_REQUEST: "pii_request",
            Intent.OUT_OF_SCOPE: "out_of_scope",
        }[decision.intent]
        main = refusal(kind)
        decision.refusal = f"{reminder} {main}" if reminder else main
        if decision.intent is Intent.ADVICE:
            decision.links = list(load_yaml("refusals.yaml").get("education_links", []))
    else:
        decision.notice = reminder
    return decision


def check_input(text: str, *, use_llm: bool | None = None) -> GuardDecision:
    """Classify a user message. Always returns the redacted text for downstream use."""
    raw = text or ""
    clean, entities = pii.redact_with_entities(raw)
    flags: set[Intent] = {Intent.PII_SHARED} if entities else set()
    pii_types = sorted({e.entity_type for e in entities})

    rule_flags, reasons = _rule_flags(normalise(clean))
    flags |= rule_flags
    source: Literal["rule", "llm", "fallback"] = "rule"

    if not rule_flags & BLOCKING:
        llm_on = get_settings().guard_llm_enabled if use_llm is None else use_llm
        result = _llm_classify(clean) if llm_on else None
        if result is not None:
            source = "llm"
            reasons.append(f"llm:{result.intent}:{result.confidence:.2f}")
            if result.intent != "ALLOWED" and result.confidence >= 0.5:
                flags.add(Intent(result.intent))
        else:
            source = "fallback"
            if not _DOMAIN.search(normalise(clean)):
                flags.add(Intent.OUT_OF_SCOPE)
                reasons.append("no_domain_keyword")

    primary = next((p for p in _PRIORITY if p in flags), Intent.ALLOWED)
    if primary is Intent.ALLOWED and Intent.PII_SHARED in flags:
        primary = Intent.PII_SHARED
    flags.add(primary)
    decision = GuardDecision(
        intent=primary,
        flags=frozenset(flags),
        clean_text=clean,
        pii_types=pii_types,
        source=source,
        reason=",".join(reasons),
    )
    _log.info(
        "guard_input",
        extra={"intent": primary.value, "flags": sorted(f.value for f in flags), "source": source},
    )
    return _compose(decision)


# --- Output validation -------------------------------------------------------------------
_OUTPUT_ADVICE = re.compile(
    r"\byou should (?:invest|buy|sell|redeem|switch|hold|consider|go for|pick|choose)\b"
    r"|\bi (?:would |'d )?(?:recommend|suggest)\b(?! (?:booking|that you book|you book))"
    r"|\b(?:best|good|top|better) (?:fund|scheme|option) (?:for you|to buy|is)\b"
    r"|\bswitch to\b|\bwill give (?:you )?(?:\d+ ?%|good|high|better) ?(?:returns?)?\b"
    r"|\bguaranteed returns?\b|\byou will (?:earn|get|make) (?:\d|returns?)",
    re.IGNORECASE,
)
_URL = re.compile(r"https?://\S+")


def output_violations(text: str) -> list[str]:
    found: list[str] = []
    if m := _OUTPUT_ADVICE.search(text or ""):
        found.append(f"advice_phrase:{m.group(0).lower()}")
    if pii.contains_pii(_URL.sub(" ", text or "")):
        found.append("pii_in_output")
    return found


def check_output(text: str) -> OutputCheck:
    """Validate generated text. On violation, `safe_text` is the standard safe fallback."""
    problems = output_violations(text)
    if problems:
        _log.warning("guard_output_violation", extra={"violations": problems})
        return OutputCheck(False, problems, refusal("safe_fallback"))
    return OutputCheck(True, [], text)
