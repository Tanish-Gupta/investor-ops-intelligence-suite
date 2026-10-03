"""Small text helpers shared by the composer and the validator."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

# ₹1,00,000 / Rs. 5,000 / 0.0060% / 243 / 3-year. Dates and doc ids are stripped first.
_NUMBER = re.compile(r"(?<![\w.])(?:₹|rs\.?\s*)?(\d{1,3}(?:,\d{2,3})+|\d+)(?:\.(\d+))?", re.I)
_IGNORE = re.compile(
    r"\b\d{4}-\d{2}-\d{2}\b"  # ISO dates (freshness line)
    r"|\b[A-Z]{1,4}(?:-[A-Z]+)+-\d+\b"  # doc ids such as FE-EXIT-01
    r"|SEBI/[\w/]+"  # circular numbers
    r"|\[\d+\]",  # citation markers
)
_WORD = re.compile(r"\S+")


def numbers(text: str) -> set[Decimal]:
    """Numeric values in `text`, normalised (₹1,00,000 == 100000, 0.0060 == 0.006)."""
    out: set[Decimal] = set()
    for m in _NUMBER.finditer(_IGNORE.sub(" ", text or "")):
        raw = m.group(1).replace(",", "") + (f".{m.group(2)}" if m.group(2) else "")
        try:
            out.add(Decimal(raw).normalize())
        except InvalidOperation:
            continue
    return out


def word_count(text: str) -> int:
    return len(_WORD.findall(text or ""))


def trim_words(text: str, limit: int = 30) -> str:
    """Trim to `limit` words, preferring a sentence boundary."""
    words = _WORD.findall(text or "")
    if len(words) <= limit:
        return text.strip()
    cut = " ".join(words[:limit])
    end = max(cut.rfind(". "), cut.rfind("; "))
    if end > len(cut) // 2:
        return cut[: end + 1].strip()
    return cut.rstrip(",;:") + "…"


def first_sentences(text: str, limit: int = 30) -> str:
    """Leading sentences of `text` (Markdown bold stripped) within `limit` words."""
    clean = re.sub(r"\*\*([^*]+)\*\*", r"\1", text or "")
    clean = re.sub(r"\s+", " ", clean).strip()
    out = ""
    for sent in re.split(r"(?<=[.!?])\s+", clean):
        cand = f"{out} {sent}".strip()
        if word_count(cand) > limit:
            break
        out = cand
    return out or trim_words(clean, limit)
