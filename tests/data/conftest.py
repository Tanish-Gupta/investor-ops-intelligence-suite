"""Helpers shared by the Phase 2 data tests: load the registry and resolve doc text."""

from __future__ import annotations

import csv
import re
import unicodedata
from functools import cache
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
CONFIG = ROOT / "config"
SOURCES = DATA / "sources.csv"

_QUOTES = str.maketrans({"\u2019": "'", "\u2018": "'", "\u201c": '"', "\u201d": '"'})


def normalise(text: str) -> str:
    """Fold quotes, bold markers and whitespace so evidence strings match the corpus."""
    text = unicodedata.normalize("NFKC", text).translate(_QUOTES).replace("**", "")
    return re.sub(r"\s+", " ", text).strip().lower()


@cache
def sources() -> dict[str, dict[str, str]]:
    with SOURCES.open(encoding="utf-8", newline="") as f:
        return {row["doc_id"]: row for row in csv.DictReader(f)}


def slug(heading: str) -> str:
    s = re.sub(r"[^\w\s-]", "", heading.strip().lower())
    return re.sub(r"\s+", "-", s)


@cache
def fee_sections() -> dict[str, str]:
    """Map each `## Heading` anchor in fee_explainer.md to its section text."""
    text = (DATA / "corpus" / "fee_explainer.md").read_text(encoding="utf-8")
    out: dict[str, str] = {}
    for block in re.split(r"(?m)^## ", text)[1:]:
        heading, _, body = block.partition("\n")
        out[slug(heading)] = body
    return out


def doc_text(doc_id: str) -> str:
    row = sources()[doc_id]
    path, _, anchor = row["local_path"].partition("#")
    if anchor:
        return fee_sections()[anchor]
    p = ROOT / path
    if p.suffix in {".html", ".pdf"}:
        p = DATA / "corpus" / "text" / f"{doc_id}.md"
    return p.read_text(encoding="utf-8")


def load_yaml(name: str) -> dict:
    return yaml.safe_load((CONFIG / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def registry() -> dict[str, dict[str, str]]:
    return sources()
