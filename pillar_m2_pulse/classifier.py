"""Theme classifier: batched LLM (opt-in, schema-constrained) with a deterministic keyword fallback.

Every review gets exactly one taxonomy label. The LLM path is used only when
`PULSE_LLM_ENABLED=true` and a key is configured; any failure or a confidence below
`pulse_min_confidence` falls back to keyword rules for that review.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel, Field, create_model

from config.settings import get_settings
from core import llm
from core.prompts import load_prompt

from .taxonomy import Taxonomy, load_taxonomy

_log = logging.getLogger(__name__)
PROMPT = "theme_classifier.v1.md"


@dataclass(frozen=True)
class Classification:
    theme: str
    secondary_theme: str | None
    sentiment: float
    confidence: float
    method: str  # "llm" | "keyword"


# --- keyword fallback -------------------------------------------------------------------------


def classify_keywords(
    text: str, rating: int | None = None, tax: Taxonomy | None = None
) -> Classification:
    tax = tax or load_taxonomy()
    scores: list[tuple[int, int, str]] = []
    for order, theme in enumerate(tax.themes):
        if theme.pattern is None:
            continue
        hits = len(theme.pattern.findall(text or ""))
        if hits:
            scores.append((hits, -order, theme.label))
    scores.sort(reverse=True)
    sentiment = round(((rating or 3) - 3) / 2, 2)
    if not scores:
        return Classification(tax.fallback_label, None, sentiment, 0.3, "keyword")
    best = scores[0]
    second = scores[1][2] if len(scores) > 1 else None
    margin = best[0] - (scores[1][0] if len(scores) > 1 else 0)
    confidence = min(0.95, 0.6 + 0.1 * best[0] + 0.05 * margin)
    return Classification(best[2], second, sentiment, round(confidence, 2), "keyword")


# --- LLM path ---------------------------------------------------------------------------------


@lru_cache(maxsize=4)
def _batch_schema(labels: tuple[str, ...]) -> type[BaseModel]:
    label_t = Literal[labels]  # type: ignore[valid-type]
    item = create_model(
        "ThemeItem",
        id=(str, ...),
        theme=(label_t, ...),
        secondary_theme=(label_t | None, None),
        sentiment=(float, Field(0.0, ge=-1, le=1)),
        confidence=(float, Field(0.5, ge=0, le=1)),
    )
    return create_model("ThemeBatch", items=(list[item], ...))  # type: ignore[valid-type]


def _system_prompt(tax: Taxonomy) -> str:
    lines = [f"- {t.label}: {t.description}" for t in tax.themes]
    return load_prompt(PROMPT).replace("{taxonomy}", "\n".join(lines))


def _cache_key(text: str, tax: Taxonomy) -> str:
    return hashlib.sha1(f"{tax.version}|{text}".encode()).hexdigest()


class ThemeCache:
    """Small JSON cache keyed by taxonomy version + review text hash (re-runs are free)."""

    def __init__(self, path=None):
        self.path = path
        self.data: dict[str, dict[str, Any]] = {}
        if path and path.exists():
            try:
                self.data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                self.data = {}

    def get(self, key: str) -> Classification | None:
        hit = self.data.get(key)
        return Classification(**hit) if hit else None

    def put(self, key: str, value: Classification) -> None:
        self.data[key] = value.__dict__.copy()

    def save(self) -> None:
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.data), encoding="utf-8")


def _llm_batch(rows: list[tuple[str, str]], tax: Taxonomy) -> dict[str, Classification]:
    schema = _batch_schema(tax.labels)
    payload = json.dumps([{"id": i, "review": t[:600]} for i, t in rows], ensure_ascii=False)
    result = llm.complete(_system_prompt(tax), f"Reviews:\n{payload}", schema=schema)
    out: dict[str, Classification] = {}
    for it in result.items:  # type: ignore[attr-defined]
        sec = it.secondary_theme if it.secondary_theme != it.theme else None
        out[it.id] = Classification(
            it.theme, sec, round(it.sentiment, 2), round(it.confidence, 2), "llm"
        )
    return out


def classify_frame(
    df: pd.DataFrame,
    *,
    use_llm: bool | None = None,
    cache: ThemeCache | None = None,
    progress: Callable[[float], None] | None = None,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Add theme / secondary_theme / sentiment / confidence / method columns to `df`."""
    settings = get_settings()
    tax = load_taxonomy()
    if use_llm is None:
        use_llm = settings.pulse_llm_enabled
    use_llm = bool(use_llm) and llm.llm_available()
    texts = [
        f"{t} — {x}".strip(" —") if t else x for t, x in zip(df["title"], df["text"], strict=True)
    ]
    ratings = df["rating"].tolist()
    results: list[Classification | None] = [None] * len(df)
    stats = {"llm": 0, "keyword": 0, "cached": 0, "llm_errors": 0, "low_conf_fallback": 0}

    if use_llm:
        cache = cache or ThemeCache()
        todo: list[int] = []
        for i, text in enumerate(texts):
            hit = cache.get(_cache_key(text, tax))
            if hit:
                results[i] = hit
                stats["cached"] += 1
            else:
                todo.append(i)
        size = settings.pulse_llm_batch
        for start in range(0, len(todo), size):
            idx = todo[start : start + size]
            try:
                got = _llm_batch([(str(i), texts[i]) for i in idx], tax)
            except llm.LLMError as exc:
                stats["llm_errors"] += 1
                _log.warning("theme_llm_batch_failed", extra={"error": str(exc)[:120]})
                got = {}
            for i in idx:
                c = got.get(str(i))
                if c is not None:
                    results[i] = c
                    cache.put(_cache_key(texts[i], tax), c)
            if progress:
                progress(min(1.0, (start + size) / max(len(todo), 1)))
        cache.save()

    min_conf = settings.pulse_min_confidence
    for i, text in enumerate(texts):
        c = results[i]
        if c is not None and c.confidence < min_conf:
            stats["low_conf_fallback"] += 1
            kw = classify_keywords(text, ratings[i], tax)
            c = kw if kw.theme != tax.fallback_label else c
        if c is None:
            c = classify_keywords(text, ratings[i], tax)
        if c.theme not in tax.labels:
            c = Classification(tax.fallback_label, None, c.sentiment, c.confidence, c.method)
        results[i] = c
        stats["llm" if c.method == "llm" else "keyword"] += 1

    out = df.copy()
    out["theme"] = [c.theme for c in results]  # type: ignore[union-attr]
    out["secondary_theme"] = [c.secondary_theme for c in results]  # type: ignore[union-attr]
    out["sentiment"] = [c.sentiment for c in results]  # type: ignore[union-attr]
    out["confidence"] = [c.confidence for c in results]  # type: ignore[union-attr]
    out["method"] = [c.method for c in results]  # type: ignore[union-attr]
    return out, stats
