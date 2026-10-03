"""Versioned prompt / template loader. Prompts live in `prompts/` as files, never inline."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from config.settings import ROOT_DIR

PROMPTS_DIR = ROOT_DIR / "prompts"


@lru_cache
def load_prompt(name: str) -> str:
    """Load `prompts/<name>` (e.g. 'guardrail_classifier.v1.md')."""
    return (PROMPTS_DIR / name).read_text(encoding="utf-8").strip()


@lru_cache
def load_yaml(name: str) -> dict[str, Any]:
    data = yaml.safe_load((PROMPTS_DIR / name).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{name} must contain a mapping")
    return data


def refusal(kind: str, **fmt: str) -> str:
    """Return the standard refusal text for `kind` (advice, pii_request, ...)."""
    text = load_yaml("refusals.yaml")[kind]
    return " ".join(str(text).split()).format(**fmt) if fmt else " ".join(str(text).split())


def prompt_path(name: str) -> Path:
    return PROMPTS_DIR / name
