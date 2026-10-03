"""Retrieval: pinned chunks + LanceDB hybrid search (vector + FTS, RRF) + cross-encoder rerank.

Pinned chunks come from deterministic lookups: the factsheet field card for a FACT
sub-query and the fee-explainer section for a FEE sub-query. Hybrid search adds supporting
context (regulator pages, other chunks) pre-filtered by `source_type` and scheme. Every
candidate is scored by bge-reranker-v2-m3. That score drives the MIN_RELEVANCE threshold.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, replace
from typing import Any

from config.settings import get_settings
from pillar_a_kb import models
from pillar_a_kb.corpus import Scheme
from pillar_a_kb.ingest import open_table
from pillar_a_kb.router import SubQuery

_log = logging.getLogger(__name__)

MAX_CONTEXT = 8
_COLS = [
    "chunk_id",
    "doc_id",
    "source_type",
    "scheme",
    "category",
    "field",
    "fee_type",
    "url",
    "title",
    "fetched_on",
    "as_of",
    "text",
]


class IndexNotBuilt(RuntimeError):
    """`kb_unified` does not exist yet (run `python -m pillar_a_kb.ingest`)."""


@dataclass(frozen=True)
class Retrieved:
    chunk_id: str
    doc_id: str
    source_type: str
    scheme: str
    field: str
    fee_type: str
    url: str
    title: str
    fetched_on: str
    text: str
    score: float = 0.0  # reranker relevance in [0, 1]
    pinned: bool = False
    sub_query: str = ""

    @property
    def is_m1(self) -> bool:
        return self.source_type.startswith("M1_")

    @property
    def is_m2(self) -> bool:
        return self.source_type.startswith("M2_")


def _row(r: dict[str, Any], **kw: Any) -> Retrieved:
    return Retrieved(**{k: r[k] for k in _COLS if k in Retrieved.__dataclass_fields__}, **kw)


def _sql_list(values: list[str]) -> str:
    return ", ".join("'" + v.replace("'", "''") + "'" for v in values)


def _fts_text(text: str) -> str:
    return re.sub(r"[^\w%₹. ]+", " ", text).strip() or "mutual fund"


class Retriever:
    def __init__(self, table: Any | None = None) -> None:
        self.table = table if table is not None else open_table()
        if self.table is None:
            raise IndexNotBuilt("kb_unified not built")
        self.settings = get_settings()
        self.degraded = False  # True after a search ran without the local models

    def by_ids(self, chunk_ids: list[str]) -> list[Retrieved]:
        if not chunk_ids:
            return []
        rows = (
            self.table.search()
            .where(f"chunk_id IN ({_sql_list(chunk_ids)})")
            .limit(len(chunk_ids))
            .select(_COLS)
            .to_list()
        )
        order = {c: i for i, c in enumerate(chunk_ids)}
        return sorted((_row(r, pinned=True) for r in rows), key=lambda r: order[r.chunk_id])

    def _filter(self, sq: SubQuery, scheme: Scheme | None) -> str:
        if sq.type == "FACT":
            where = "source_type = 'M1_FACTSHEET'"
            if scheme:
                where += f" AND scheme = {_sql_list([scheme.canonical])}"
            return where
        where = "source_type IN ('M2_FEE_EXPLAINER', 'M1_REGULATOR')"
        if scheme:
            where += f" AND category IN ({_sql_list([scheme.category, 'ALL'])})"
        return where

    def hybrid(self, sq: SubQuery, scheme: Scheme | None, limit: int) -> list[Retrieved]:
        from lancedb.rerankers import RRFReranker

        vec = models.embed_query(sq.text)
        rows = (
            self.table.search(query_type="hybrid")
            .vector(vec)
            .text(_fts_text(sq.text))
            .where(self._filter(sq, scheme), prefilter=True)
            .rerank(RRFReranker())
            .limit(limit)
            .to_list()
        )
        return [_row(r, sub_query=sq.text) for r in rows]

    def retrieve(
        self,
        sub_queries: list[SubQuery],
        scheme: Scheme | None,
        pinned_ids: list[str],
        *,
        query: str,
    ) -> list[Retrieved]:
        """Pinned chunks first, then the best reranked search hits (deduped, ≤ MAX_CONTEXT)."""
        s = self.settings
        self.degraded = False
        pinned = self.by_ids(pinned_ids)
        seen = {p.chunk_id for p in pinned}
        candidates: list[Retrieved] = []
        try:
            for sq in sub_queries:
                for hit in self.hybrid(sq, scheme, s.rerank_candidates):
                    if hit.chunk_id not in seen:
                        seen.add(hit.chunk_id)
                        candidates.append(hit)
            scored = self._score(query, pinned + candidates)
        except models.ModelUnavailable as exc:  # degrade: deterministic pins only
            _log.warning("kb_models_unavailable", extra={"error": str(exc)[:200]})
            self.degraded = True
            return [replace(p, score=1.0) for p in pinned]
        pinned_scored = scored[: len(pinned)]
        found = sorted(scored[len(pinned) :], key=lambda r: -r.score)
        found = [r for r in found if r.score >= s.min_relevance][: s.top_k]
        out = (pinned_scored + found)[: max(MAX_CONTEXT, len(pinned_scored))]
        _log.info(
            "kb_retrieve",
            extra={
                "pinned": len(pinned),
                "candidates": len(candidates),
                "kept": len(out),
                "top": round(max((r.score for r in out), default=0), 3),
            },
        )
        return out

    def _score(self, query: str, items: list[Retrieved]) -> list[Retrieved]:
        if not items:
            return []
        if not self.settings.rerank_enabled:
            return [replace(r, score=1.0 if r.pinned else 0.5) for r in items]
        scores = models.rerank(query, [r.text for r in items])
        return [replace(r, score=sc) for r, sc in zip(items, scores, strict=True)]

    def search(self, query: str, scheme: Scheme | None = None) -> list[Retrieved]:
        """Open search across the whole corpus (no deterministic pins)."""
        subs = [SubQuery("FEE", query), SubQuery("FACT", query)]
        return self.retrieve(subs, scheme, [], query=query)


_retriever: Retriever | None = None


def get_retriever(refresh: bool = False) -> Retriever:
    global _retriever
    if _retriever is None or refresh:
        _retriever = Retriever()
    return _retriever
