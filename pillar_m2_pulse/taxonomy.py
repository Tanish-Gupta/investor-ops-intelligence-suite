"""Fixed theme taxonomy (`config/themes.yaml`) shared by the classifier, pulse and voice agent."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import yaml

from config.settings import ROOT_DIR

THEMES_PATH = ROOT_DIR / "config" / "themes.yaml"


@dataclass(frozen=True)
class Theme:
    label: str
    description: str
    keywords: tuple[str, ...]
    voice_topic: str | None
    bookable_from_greeting: bool
    greeting_phrase: str
    action_idea: str
    pattern: re.Pattern[str] | None


@dataclass(frozen=True)
class Taxonomy:
    themes: tuple[Theme, ...]
    fallback_label: str
    max_active_themes: int
    booking_topics: tuple[str, ...]
    version: str

    @property
    def labels(self) -> tuple[str, ...]:
        return tuple(t.label for t in self.themes)

    def get(self, label: str | None) -> Theme | None:
        return next((t for t in self.themes if t.label == label), None)


def _keyword_pattern(keywords: list[str]) -> re.Pattern[str] | None:
    if not keywords:
        return None
    parts = sorted({re.escape(k.lower()).replace(r"\ ", r"[\s-]+") for k in keywords}, key=len)
    alts = "|".join(reversed(parts))
    return re.compile(rf"(?<![\w])(?:{alts})(?:s|es|ed|ing)?(?![\w])", re.IGNORECASE)


@lru_cache(maxsize=1)
def load_taxonomy() -> Taxonomy:
    raw_text = THEMES_PATH.read_text(encoding="utf-8")
    cfg: dict[str, Any] = yaml.safe_load(raw_text)
    themes = tuple(
        Theme(
            label=t["label"],
            description=t.get("description", ""),
            keywords=tuple(t.get("keywords") or ()),
            voice_topic=t.get("voice_topic"),
            bookable_from_greeting=bool(t.get("bookable_from_greeting")),
            greeting_phrase=t.get("greeting_phrase") or t["label"].lower(),
            action_idea=t.get("action_idea", ""),
            pattern=_keyword_pattern(list(t.get("keywords") or ())),
        )
        for t in cfg["themes"]
    )
    return Taxonomy(
        themes=themes,
        fallback_label=cfg.get("fallback_label", "Other"),
        max_active_themes=int(cfg.get("max_active_themes", 5)),
        booking_topics=tuple(cfg.get("booking_topics") or ()),
        version=hashlib.sha1(raw_text.encode()).hexdigest()[:10],
    )
