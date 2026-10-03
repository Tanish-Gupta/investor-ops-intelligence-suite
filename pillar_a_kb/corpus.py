"""Corpus registry and config loaders for Pillar A.

`data/sources.csv` is the single list of documents. Each row resolves to Markdown text:
- `F-*` scheme captures: `data/corpus/schemes/<doc_id>.md`
- `R-*` regulator pages: `data/corpus/text/<doc_id>.md` (extracted from the raw HTML/PDF)
- `FE-*` fee explainer: one `##` section of `data/corpus/fee_explainer.md`
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from config.settings import ROOT_DIR, get_settings

FRONT_MATTER_RE = re.compile(r"\A---\n.*?\n---\n", re.DOTALL)
_FEE_DOC_LINE = re.compile(r"^doc_id:\s*(FE-[A-Z]+-\d+)\s*·\s*fee_type:\s*(\w+)\s*$", re.M)

FACT_TYPES = frozenset({"M1_FACTSHEET"})
FEE_TYPES = frozenset({"M2_FEE_EXPLAINER", "M1_REGULATOR"})


@dataclass(frozen=True)
class Source:
    doc_id: str
    url: str
    title: str
    scheme: str  # canonical scheme name, or "ALL"
    category: str
    source_type: str
    fetched_on: str
    as_of: str
    local_path: str
    fetch_method: str

    @property
    def is_m1(self) -> bool:
        return self.source_type.startswith("M1_")

    @property
    def is_m2(self) -> bool:
        return self.source_type.startswith("M2_")

    @property
    def short_title(self) -> str:
        """Compact label for bullet 6 / source chips."""
        t = re.sub(r"\s*\([^)]*\)", "", self.title).replace("Fee Explainer: ", "Fee Explainer – ")
        if self.source_type == "M1_REGULATOR" and ":" in t:
            publisher, topic = (p.strip() for p in t.split(":", 1))
            if publisher.startswith("SEBI circular"):
                return publisher
            short = next((v for k, v in _PUBLISHERS.items() if publisher.startswith(k)), publisher)
            return f"{short} – {topic[:1].upper()}{topic[1:]}"
        return t


_PUBLISHERS = {
    "AMFI": "AMFI",
    "Bajaj": "Bajaj AMC",
    "SEBI": "SEBI",
    "Tata": "Tata MF",
}


@dataclass(frozen=True)
class Document:
    source: Source
    text: str  # Markdown without front matter
    fee_type: str | None = None


@lru_cache
def load_sources(path: Path | None = None) -> tuple[Source, ...]:
    path = path or get_settings().data_dir / "sources.csv"
    with path.open(newline="", encoding="utf-8") as fh:
        return tuple(Source(**row) for row in csv.DictReader(fh))


def sources_by_id() -> dict[str, Source]:
    return {s.doc_id: s for s in load_sources()}


def strip_front_matter(text: str) -> str:
    return FRONT_MATTER_RE.sub("", text, count=1).strip()


def fee_sections(path: Path | None = None) -> dict[str, tuple[str, str]]:
    """doc_id -> (fee_type, section markdown including its `##` heading)."""
    path = path or get_settings().data_dir / "corpus" / "fee_explainer.md"
    body = strip_front_matter(path.read_text(encoding="utf-8"))
    out: dict[str, tuple[str, str]] = {}
    for part in re.split(r"(?m)^(?=## )", body):
        if m := _FEE_DOC_LINE.search(part):
            out[m.group(1)] = (m.group(2), part.strip())
    return out


def _text_path(src: Source) -> Path:
    base = get_settings().data_dir / "corpus"
    if src.doc_id.startswith("F-"):
        return base / "schemes" / f"{src.doc_id}.md"
    return base / "text" / f"{src.doc_id}.md"


def load_documents() -> list[Document]:
    sections = fee_sections()
    docs: list[Document] = []
    for src in load_sources():
        if src.source_type == "M2_FEE_EXPLAINER":
            fee_type, text = sections[src.doc_id]
            docs.append(Document(src, text, fee_type))
        else:
            docs.append(Document(src, strip_front_matter(_text_path(src).read_text("utf-8"))))
    return docs


# --- Config ------------------------------------------------------------------------------
def _yaml(name: str) -> dict[str, Any]:
    return yaml.safe_load((ROOT_DIR / "config" / name).read_text(encoding="utf-8"))


@lru_cache
def fee_rules() -> dict[str, Any]:
    return _yaml("fee_rules.yaml")


@dataclass(frozen=True)
class Scheme:
    id: str
    canonical: str
    category: str
    doc_ids: tuple[str, ...]
    aliases: tuple[str, ...]


@lru_cache
def schemes() -> tuple[Scheme, ...]:
    raw = _yaml("scheme_aliases.yaml")["schemes"]
    return tuple(
        Scheme(s["id"], s["canonical"], s["category"], tuple(s["doc_ids"]), tuple(s["aliases"]))
        for s in raw
    )


def scheme_by_id(scheme_id: str) -> Scheme:
    return next(s for s in schemes() if s.id == scheme_id)


def scheme_by_name(name: str) -> Scheme | None:
    return next((s for s in schemes() if s.canonical == name), None)


def fee_explainer_doc(fee_type: str) -> str | None:
    """Fee explainer doc_id for a fee type (graded exit load handled by the caller)."""
    for doc_id, (ft, _) in fee_sections().items():
        if ft == fee_type and doc_id != "FE-GRADED-01":
            return doc_id
    return None


_PART = re.compile(
    r"\*\*(What it is|How it is calculated|How it is used|Worked example|"
    r"Why was I charged it\?)\.?\*\*\s*(.+?)(?=\n\*\*|\n\| |\nSource:|\Z)",
    re.S,
)
_PART_KEYS = {
    "What it is": "what",
    "How it is calculated": "how",
    "How it is used": "how",
    "Worked example": "example",
    "Why was I charged it?": "why",
}


@lru_cache
def explainer_parts(doc_id: str) -> dict[str, str]:
    """`what` / `how` / `example` / `why` paragraphs of one fee-explainer section."""
    _, text = fee_sections()[doc_id]
    return {
        _PART_KEYS[m.group(1)]: re.sub(r"\s+", " ", m.group(2)).strip()
        for m in _PART.finditer(text)
    }
