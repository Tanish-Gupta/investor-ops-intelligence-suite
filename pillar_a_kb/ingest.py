"""Ingest the corpus into LanceDB `kb_unified` (vector + full-text) and `scheme_facts` (SQLite).

Smart-Sync: each document is hashed. A re-run only re-embeds documents whose text changed,
deletes chunks of documents removed from `sources.csv`, then refreshes the full-text index.
So after a factsheet refresh (`scripts/fetch_corpus.py`), `python -m pillar_a_kb.ingest`
updates just that scheme.

    python -m pillar_a_kb.ingest            # incremental sync
    python -m pillar_a_kb.ingest --rebuild  # drop and rebuild everything
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import time
from dataclasses import asdict, dataclass
from io import BytesIO
from typing import Any

from config.settings import get_settings
from core.state import now
from pillar_a_kb import models
from pillar_a_kb.corpus import Document, load_documents
from pillar_a_kb.facts import FIELD_LABELS, Fact, extract_doc, sync_to_db

_log = logging.getLogger(__name__)

CHUNKER_VERSION = "hybrid-400-v1"  # bump to force re-chunking of every document
MAX_TOKENS = 400
MIN_TOKENS = 15


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    source_type: str
    scheme: str
    category: str
    field: str
    fee_type: str
    url: str
    title: str
    fetched_on: str
    as_of: str
    text: str
    doc_hash: str


def doc_hash(doc: Document) -> str:
    return hashlib.sha256(f"{CHUNKER_VERSION}\n{doc.text}".encode()).hexdigest()[:16]


def _base(doc: Document, h: str) -> dict[str, Any]:
    s = doc.source
    return dict(
        doc_id=s.doc_id,
        source_type=s.source_type,
        scheme=s.scheme,
        category=s.category,
        url=s.url,
        title=s.title,
        fetched_on=s.fetched_on,
        as_of=s.as_of,
        doc_hash=h,
    )


# --- Chunking -----------------------------------------------------------------------------
class _Docling:
    """Docling Markdown parser + HybridChunker using the embedding model's tokenizer."""

    def __init__(self) -> None:
        models.configure_hf_env()
        from docling.chunking import HybridChunker
        from docling.datamodel.base_models import InputFormat
        from docling.document_converter import DocumentConverter
        from docling_core.transforms.chunker.tokenizer.huggingface import HuggingFaceTokenizer
        from transformers import AutoTokenizer

        tok = AutoTokenizer.from_pretrained(get_settings().embed_model)
        self.tokenizer = HuggingFaceTokenizer(tokenizer=tok, max_tokens=MAX_TOKENS)
        self.chunker = HybridChunker(tokenizer=self.tokenizer, merge_peers=True)
        self.converter = DocumentConverter(allowed_formats=[InputFormat.MD])

    def chunk(self, doc_id: str, markdown: str) -> list[str]:
        from docling_core.types.io import DocumentStream

        stream = DocumentStream(name=f"{doc_id}.md", stream=BytesIO(markdown.encode("utf-8")))
        dl_doc = self.converter.convert(stream).document
        texts = []
        for c in self.chunker.chunk(dl_doc):
            if self.tokenizer.count_tokens(c.text) >= MIN_TOKENS:
                texts.append(self.chunker.contextualize(c))
        return texts


def field_cards(doc: Document, facts: list[Fact], h: str) -> list[Chunk]:
    """One small chunk per labelled factsheet field so FACT lookups have an exact citation."""
    cards = []
    for f in facts:
        if f.field == "min_lumpsum":  # same source line as min_sip
            continue
        field = "min_investment" if f.field == "min_sip" else f.field
        label = (
            "Minimum investment (lump sum / SIP)"
            if field == "min_investment"
            else (FIELD_LABELS.get(field, field))
        )
        text = f"{f.scheme} — {label}\n{f.evidence}"
        cards.append(
            Chunk(
                chunk_id=f"{doc.source.doc_id}#{field}",
                field=field,
                fee_type="",
                text=text,
                **_base(doc, h),
            )
        )
    return cards


def build_chunks(doc: Document, docling: _Docling | None) -> list[Chunk]:
    h = doc_hash(doc)
    src = doc.source
    if src.source_type == "M2_FEE_EXPLAINER":  # one chunk per fee type (already 200-400 tokens)
        return [
            Chunk(
                chunk_id=src.doc_id,
                field="",
                fee_type=doc.fee_type or "",
                text=doc.text,
                **_base(doc, h),
            )
        ]
    facts = extract_doc(doc)
    cards = field_cards(doc, facts, h)
    body = docling.chunk(src.doc_id, doc.text) if docling else _heading_chunks(doc.text)
    prefix = f"{src.title}\n"
    chunks = [
        Chunk(
            chunk_id=f"{src.doc_id}#c{i:03d}",
            field="",
            fee_type="",
            text=prefix + t,
            **_base(doc, h),
        )
        for i, t in enumerate(body)
    ]
    return cards + chunks


def _heading_chunks(markdown: str, max_words: int = 280) -> list[str]:
    """Fallback splitter (no tokenizer): split on headings, then on paragraphs."""
    import re

    out: list[str] = []
    for sec in re.split(r"(?m)^(?=#{1,3} )", markdown):
        buf: list[str] = []
        for para in sec.split("\n\n"):
            if sum(len(p.split()) for p in buf) + len(para.split()) > max_words and buf:
                out.append("\n\n".join(buf))
                buf = []
            buf.append(para)
        if buf and len(" ".join(buf).split()) >= MIN_TOKENS:
            out.append("\n\n".join(buf))
    return out


# --- LanceDB ------------------------------------------------------------------------------
def connect() -> Any:
    import lancedb

    path = get_settings().lancedb_dir
    path.mkdir(parents=True, exist_ok=True)
    return lancedb.connect(str(path))


def _tables(db: Any) -> list[str]:
    res = db.list_tables()
    return list(getattr(res, "tables", res))


def open_table() -> Any | None:
    db = connect()
    name = get_settings().kb_table
    return db.open_table(name) if name in _tables(db) else None


def _existing_hashes(table: Any) -> dict[str, str]:
    if table is None:
        return {}
    df = table.to_pandas()[["doc_id", "doc_hash"]].drop_duplicates()
    return dict(zip(df.doc_id, df.doc_hash, strict=True))


def manifest_path() -> Any:
    return get_settings().lancedb_dir / "ingest_manifest.json"


def read_manifest() -> dict[str, Any] | None:
    p = manifest_path()
    return json.loads(p.read_text()) if p.exists() else None


def ingest(*, rebuild: bool = False, use_docling: bool = True) -> dict[str, Any]:
    from lancedb.index import FTS

    started = time.monotonic()
    docs = load_documents()
    db = connect()
    name = get_settings().kb_table
    if rebuild and name in _tables(db):
        db.drop_table(name)
    table = open_table()
    old = _existing_hashes(table)
    current = {d.source.doc_id: doc_hash(d) for d in docs}
    changed = [d for d in docs if old.get(d.source.doc_id) != current[d.source.doc_id]]
    removed = sorted(set(old) - set(current))

    docling = _Docling() if use_docling and changed else None
    chunks = [c for d in changed for c in build_chunks(d, docling)]
    if chunks:
        vectors = models.embed_documents([c.text for c in chunks])
        rows = [{**asdict(c), "vector": v} for c, v in zip(chunks, vectors, strict=True)]
    else:
        rows = []

    stale = [d.source.doc_id for d in changed if d.source.doc_id in old] + removed
    if table is None:
        table = db.create_table(name, data=rows)
    else:
        if stale:
            ids = ", ".join(f"'{i}'" for i in stale)
            table.delete(f"doc_id IN ({ids})")
        if rows:
            table.add(rows)
    if rows or stale:
        table.create_index("text", config=FTS(), replace=True)

    facts = sync_to_db()
    report = {
        "built_at": now().isoformat(timespec="seconds"),
        "table": name,
        "documents": len(docs),
        "updated_documents": [d.source.doc_id for d in changed],
        "removed_documents": removed,
        "chunks_written": len(rows),
        "total_chunks": table.count_rows(),
        "scheme_facts": facts,
        "chunker": CHUNKER_VERSION if use_docling else "heading-fallback",
        "embed_model": get_settings().embed_model,
        "seconds": round(time.monotonic() - started, 1),
    }
    if rows or stale or not manifest_path().exists():
        manifest_path().write_text(json.dumps(report, indent=2))
    _log.info("kb_ingest", extra={k: v for k, v in report.items() if k != "updated_documents"})
    return report


def _main() -> None:
    from core.logging import configure_logging

    configure_logging()
    ap = argparse.ArgumentParser(description="Build / sync the Pillar A knowledge base.")
    ap.add_argument("--rebuild", action="store_true", help="drop the table and re-embed all")
    ap.add_argument("--no-docling", action="store_true", help="use the heading splitter")
    args = ap.parse_args()
    print(json.dumps(ingest(rebuild=args.rebuild, use_docling=not args.no_docling), indent=2))


if __name__ == "__main__":
    _main()
