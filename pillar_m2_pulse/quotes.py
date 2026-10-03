"""Pick one representative, PII-safe quote per top theme (10–40 words, attributed anonymously)."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from core import guardrails, pii

MIN_Q, MAX_Q = 10, 40


@dataclass(frozen=True)
class Quote:
    theme: str
    text: str
    rating: int
    review_id: str

    def render(self, max_words: int = MAX_Q) -> str:
        return f'"{shorten(self.text, max_words)}" — {pii.REDACTED}, ★{self.rating}'


def shorten(text: str, max_words: int) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]).rstrip(",;:.!?-—") + "…"


def _clean(text: str) -> str:
    return " ".join(str(text).replace('"', "'").split())


def select_quotes(df: pd.DataFrame, themes: list[str]) -> list[Quote]:
    """Deterministic: low rating first (the issue), then confidence, then closeness to 25 words."""
    quotes: list[Quote] = []
    for theme in themes:
        sub = df[df["theme"] == theme].copy()
        if sub.empty:
            continue
        sub["_words"] = sub["text"].str.split().str.len()
        safe = sub["text"].map(lambda t: not guardrails.output_violations(t))
        if safe.any():  # never quote advice-like phrasing ("I'd recommend this fund")
            sub = sub[safe]
        unredacted = ~sub["text"].str.contains(r"\[REDACTED\]", regex=True)
        if unredacted.any():  # prefer quotes that needed no masking
            sub = sub[unredacted]
        in_range = sub[sub["_words"].between(MIN_Q, MAX_Q)]
        pool = in_range if not in_range.empty else sub
        pool = pool.assign(_dist=(pool["_words"] - 25).abs())
        conf = pool["confidence"] if "confidence" in pool else 0
        pool = pool.assign(_conf=conf).sort_values(
            ["rating", "_conf", "_dist", "review_id"], ascending=[True, False, True, True]
        )
        row = pool.iloc[0]
        text = pii.redact(shorten(_clean(row["text"]), MAX_Q))
        quotes.append(Quote(theme, text, int(row["rating"]), str(row["review_id"])))
    return quotes
