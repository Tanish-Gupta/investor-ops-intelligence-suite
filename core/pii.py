"""PII detection and masking (rules P1–P7) built on Microsoft Presidio.

Every boundary (review ingest, user input, LLM output, storage, logs, MCP payloads) calls
`redact()` / `scrub()`. Each detected entity becomes the literal `[REDACTED]`.

Recognizers:
- Presidio built-ins: EMAIL_ADDRESS, CREDIT_CARD (Luhn), PHONE_NUMBER (IN), IN_PAN,
  IN_AADHAAR (Verhoeff checksum).
- Custom (ported from the M2/M3 regex scrubbers): strict PAN, Indian mobile, UPI ID,
  folio/account numbers with context words, long digit groups (>= 9 digits), spoken digit
  strings, and context-based person names ("my name is …", "mera naam …", "Mr. …").
- spaCy NER PERSON, only when a real spaCy model is installed and configured via
  `PII_NLP_MODEL`. The default `blank:en` pipeline needs no download; this loader never
  downloads models.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import spacy
from presidio_analyzer import (
    AnalyzerEngine,
    EntityRecognizer,
    Pattern,
    PatternRecognizer,
    RecognizerRegistry,
    RecognizerResult,
)
from presidio_analyzer.nlp_engine import NlpArtifacts, SpacyNlpEngine
from presidio_analyzer.predefined_recognizers import (
    CreditCardRecognizer,
    EmailRecognizer,
    InAadhaarRecognizer,
    InPanRecognizer,
    PhoneRecognizer,
    SpacyRecognizer,
)
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig

from config.settings import get_settings

REDACTED = "[REDACTED]"

_log = logging.getLogger(__name__)

ENTITIES: tuple[str, ...] = (
    "PERSON",
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "IN_MOBILE",
    "CREDIT_CARD",
    "IN_PAN",
    "IN_AADHAAR",
    "ACCOUNT_NUMBER",
    "ID_NUMBER",
    "UPI_ID",
    "SPOKEN_DIGITS",
)

# Spans that must never be masked: booking codes, pulse IDs, ISO dates, clock times and
# existing redaction markers.
_ALLOW_RE = re.compile(
    r"\bNL-?[A-Z]\d{3}\b"
    r"|\bPULSE-\d{4}-W\d{2}\b"
    r"|\b\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2})?(?:[+-]\d{2}:\d{2})?)?\b"
    r"|\b\d{1,2}:\d{2}(?:\s?[AP]M)?\b"
    r"|\[REDACTED\]",
    re.IGNORECASE,
)

# Words that look like names after "I am" / "this is" but are not names, plus domain terms.
_NON_NAME_WORDS = frozenset(
    w.lower()
    for w in """
    a an the not just here there from calling looking trying interested unable confused
    charged worried new existing customer user investor client calling writing asking
    sure fine okay ok good happy sad facing having getting going planning wondering booked
    done back sorry glad
    hai hoon hu and or but with about for regarding to in on at my your our their
    edelweiss groww indmoney nippon hdfc icici sbi axis kotak mirae parag quant uti tata
    elss sip swp stp nav kyc nominee fund funds scheme schemes advisor support team
    """.split()
)

_NAME_TOKEN = r"[A-Za-z][a-z]+"
_INTRO_ANY_CASE = re.compile(
    r"\b(?:my name is|my name's|name is|mera naam|mera nam|naam hai|naam)\s+"
    rf"({_NAME_TOKEN}(?:\s+{_NAME_TOKEN}){{0,2}})",
    re.IGNORECASE,
)
# Only the trigger is case-insensitive; the name itself must be Capitalised ("I'm booked" ≠ name).
_INTRO_CAPITALISED = re.compile(
    r"\b(?i:i am|i'm|im|this is|it's|its)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})"
)
_HONORIFIC = re.compile(
    r"\b(?:Mr|Mrs|Ms|Miss|Dr|Shri|Smt|Sri|Kumari)\.?\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})"
)
_NAME_FIELD = re.compile(r"\bname\s*[:=]\s*([A-Za-z][a-z]+(?:\s+[A-Za-z][a-z]+){0,2})", re.I)

_ACCOUNT_CONTEXT = re.compile(
    r"\b(?:folio|account|a/c|acct|acc|demat|client id|dp id|bo id|ucc)"
    r"(?:\s*(?:no\.?|number|num|#|id))?\s*(?:is|:|-|=)?\s*"
    r"([0-9][0-9/ -]{4,22}[0-9])",
    re.IGNORECASE,
)

_NUM_WORDS = r"(?:zero|oh|one|two|three|four|five|six|seven|eight|nine|double|triple)"


@dataclass(frozen=True)
class PIIEntity:
    """A detected entity. The raw value is intentionally not kept."""

    entity_type: str
    start: int
    end: int
    score: float


class _OfflineSpacyNlpEngine(SpacyNlpEngine):
    """SpacyNlpEngine that only loads installed pipelines and never downloads models."""

    def __init__(self, model_name: str):
        super().__init__(models=[{"lang_code": "en", "model_name": model_name}])
        self._model_name = model_name

    def load(self) -> None:
        name = self._model_name
        if name.startswith("blank:"):
            nlp = spacy.blank(name.split(":", 1)[1])
        elif spacy.util.is_package(name):
            nlp = spacy.load(name)
        else:
            _log.warning("spaCy model %s not installed; PII NER disabled (blank:en)", name)
            nlp = spacy.blank("en")
        self.nlp = {"en": nlp}

    @property
    def has_ner(self) -> bool:
        return bool(self.nlp) and "ner" in self.nlp["en"].pipe_names


class _GroupRegexRecognizer(EntityRecognizer):
    """Regex recognizer that reports only capture group 1 (e.g. the number after 'folio')."""

    def __init__(self, entity: str, regexes: Iterable[re.Pattern[str]], score: float, name: str):
        self._regexes = tuple(regexes)
        self._score = score
        super().__init__(supported_entities=[entity], name=name, supported_language="en")

    def load(self) -> None:  # nothing to load
        pass

    def _accept(self, value: str) -> bool:
        return True

    def analyze(
        self, text: str, entities: list[str], nlp_artifacts: NlpArtifacts | None = None
    ) -> list[RecognizerResult]:
        results = []
        for regex in self._regexes:
            for m in regex.finditer(text):
                value = m.group(1)
                if not self._accept(value):
                    continue
                start, end = m.span(1)
                results.append(
                    RecognizerResult(self.supported_entities[0], start, end, self._score)
                )
        return results


class _NameRecognizer(_GroupRegexRecognizer):
    """Context-based PERSON detection that works without an NER model."""

    def __init__(self) -> None:
        super().__init__(
            "PERSON",
            (_INTRO_ANY_CASE, _INTRO_CAPITALISED, _HONORIFIC, _NAME_FIELD),
            score=0.85,
            name="ContextNameRecognizer",
        )

    def analyze(
        self, text: str, entities: list[str], nlp_artifacts: NlpArtifacts | None = None
    ) -> list[RecognizerResult]:
        results = []
        for regex in self._regexes:
            for m in regex.finditer(text):
                start = m.start(1)
                tokens = list(re.finditer(r"[A-Za-z]+", m.group(1)))
                kept = []
                for tok in tokens:
                    if tok.group(0).lower() in _NON_NAME_WORDS:
                        break
                    kept.append(tok)
                if not kept:
                    continue
                results.append(
                    RecognizerResult(
                        "PERSON", start + kept[0].start(), start + kept[-1].end(), self._score
                    )
                )
        return results


class _LongDigitRecognizer(PatternRecognizer):
    """Any run of >= 9 digits, optionally grouped (>= 3 digits per group): Aadhaar without a
    valid checksum, account numbers without context, cards failing Luhn, etc. (M3 parity)."""

    MIN_DIGITS = 9

    def __init__(self) -> None:
        regex = r"(?<![\w.,])\d{3,}(?:[ -]\d{3,})*(?![\w]|[.,]\d)"
        super().__init__(
            supported_entity="ID_NUMBER",
            name="LongDigitGroup",
            patterns=[Pattern("LongDigitGroup", regex, 0.5)],
        )

    def validate_result(self, pattern_text: str) -> bool | None:
        return sum(ch.isdigit() for ch in pattern_text) >= self.MIN_DIGITS


def _pattern(entity: str, name: str, regex: str, score: float) -> PatternRecognizer:
    return PatternRecognizer(
        supported_entity=entity, name=name, patterns=[Pattern(name, regex, score)]
    )


def _custom_recognizers() -> list[EntityRecognizer]:
    return [
        _pattern("IN_PAN", "PanStrict", r"\b[A-Za-z]{5}[0-9]{4}[A-Za-z]\b", 0.85),
        _pattern(
            "IN_MOBILE",
            "IndianMobile",
            r"(?<![\w])(?:\+?91[\s-]?|0)?[6-9]\d{4}[\s-]?\d{5}(?!\d)",
            0.8,
        ),
        _pattern(
            "UPI_ID",
            "UpiId",
            r"\b[\w.\-]{2,}@[A-Za-z][A-Za-z0-9]{1,63}\b(?![.\-][A-Za-z0-9])",
            0.8,
        ),
        # Any run of >= 9 digits, optionally grouped (>= 3 digits per group): Aadhaar without a
        # valid checksum, account numbers without context, card numbers failing Luhn, etc.
        _LongDigitRecognizer(),
        _pattern(
            "SPOKEN_DIGITS",
            "SpokenDigits",
            rf"\b{_NUM_WORDS}(?:[\s-]+{_NUM_WORDS}){{6,}}\b",
            0.6,
        ),
        _GroupRegexRecognizer(
            "ACCOUNT_NUMBER", (_ACCOUNT_CONTEXT,), score=0.9, name="FolioAccountRecognizer"
        ),
        _NameRecognizer(),
    ]


class PIIScrubber:
    """Presidio analyzer + anonymizer configured for this product."""

    def __init__(
        self,
        nlp_model: str = "blank:en",
        score_threshold: float = 0.4,
        allow_terms: Iterable[str] = (),
    ):
        engine = _OfflineSpacyNlpEngine(nlp_model)
        engine.load()
        registry = RecognizerRegistry(supported_languages=["en"])
        for rec in (
            EmailRecognizer(),
            CreditCardRecognizer(),
            PhoneRecognizer(supported_regions=("IN",)),
            InPanRecognizer(),
            InAadhaarRecognizer(),
            *_custom_recognizers(),
        ):
            registry.add_recognizer(rec)
        if engine.has_ner:
            registry.add_recognizer(SpacyRecognizer(supported_entities=["PERSON"]))
        self.ner_enabled = engine.has_ner
        self._threshold = score_threshold
        # Configured system identities (e.g. the advisor mailbox) are not user PII.
        self._allow_terms = {t.strip().lower() for t in allow_terms if t and t.strip()}
        self._analyzer = AnalyzerEngine(
            nlp_engine=engine, registry=registry, supported_languages=["en"]
        )
        self._anonymizer = AnonymizerEngine()

    def _analyze(self, text: str) -> list[RecognizerResult]:
        if not text or not text.strip():
            return []
        results = self._analyzer.analyze(
            text, language="en", entities=list(ENTITIES), score_threshold=self._threshold
        )
        allowed = [m.span() for m in _ALLOW_RE.finditer(text)]
        return [
            r
            for r in results
            if not any(s < r.end and r.start < e for s, e in allowed)
            and text[r.start : r.end].strip().lower() not in self._allow_terms
        ]

    @staticmethod
    def _entities(results: list[RecognizerResult]) -> list[PIIEntity]:
        found = (PIIEntity(r.entity_type, r.start, r.end, round(r.score, 2)) for r in results)
        return sorted(found, key=lambda e: (e.start, -e.end))

    def detect(self, text: str) -> list[PIIEntity]:
        return self._entities(self._analyze(text))

    def redact_with_entities(self, text: str) -> tuple[str, list[PIIEntity]]:
        results = self._analyze(text)
        if not results:
            return text, []
        anonymized = self._anonymizer.anonymize(
            text=text,
            analyzer_results=results,
            operators={"DEFAULT": OperatorConfig("replace", {"new_value": REDACTED})},
        )
        out = _ADJACENT_RE.sub(lambda m: REDACTED + _tail(m.group(0)), anonymized.text)
        return out, self._entities(results)


_ADJACENT_RE = re.compile(r"(?:\[REDACTED\][\s-]*){2,}")


def _tail(run: str) -> str:
    """Keep the whitespace that followed a merged run of adjacent [REDACTED] markers."""
    stripped = run.rstrip()
    return run[len(stripped) :]


@lru_cache(maxsize=1)
def get_scrubber() -> PIIScrubber:
    s = get_settings()
    return PIIScrubber(
        nlp_model=s.pii_nlp_model,
        score_threshold=s.pii_score_threshold,
        allow_terms=(s.advisor_email,),
    )


def detect(text: str) -> list[PIIEntity]:
    return get_scrubber().detect(text)


def redact(text: str) -> str:
    return get_scrubber().redact_with_entities(text)[0]


def redact_with_entities(text: str) -> tuple[str, list[PIIEntity]]:
    return get_scrubber().redact_with_entities(text)


def contains_pii(text: str) -> bool:
    return bool(get_scrubber()._analyze(text))


def scrub(obj: Any) -> Any:
    """Recursively redact every string inside dicts / lists / tuples (payloads, logs, rows)."""
    if isinstance(obj, str):
        return redact(obj)
    if isinstance(obj, dict):
        return {k: scrub(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [scrub(v) for v in obj]
    if isinstance(obj, tuple):
        return tuple(scrub(v) for v in obj)
    return obj
