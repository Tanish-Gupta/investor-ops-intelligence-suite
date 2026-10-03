"""Pillar A service: `answer(query)` → `KBAnswer` (docs/architecture/rag.md §4 and §6).

Pipeline: input guardrail → PII mask → router → answer frame → retrieval (pinned + hybrid +
rerank) → composer (LLM when configured, else template; extractive for open questions) →
validator (one LLM retry, then template) → output guardrail → `KBAnswer`.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Literal

from pydantic import BaseModel, Field

from config.settings import get_settings
from core.guardrails import Intent, check_input, check_output
from core.prompts import load_yaml, refusal
from pillar_a_kb import composer as comp
from pillar_a_kb.corpus import schemes, sources_by_id
from pillar_a_kb.retriever import IndexNotBuilt, Retrieved, get_retriever
from pillar_a_kb.router import RoutePlan, route
from pillar_a_kb.validator import validate

_log = logging.getLogger(__name__)

Status = Literal["ANSWERED", "PARTIAL", "NOT_FOUND", "REFUSED", "CLARIFY", "UNAVAILABLE"]


class Citation(BaseModel):
    n: int
    doc_id: str
    title: str
    url: str
    source_type: str
    fetched_on: str
    chunk_ids: list[str] = Field(default_factory=list)


class KBAnswer(BaseModel):
    status: Status
    bullets: list[str] = Field(default_factory=list)
    bullet_citations: list[list[int]] = Field(default_factory=list)  # citation numbers
    citations: list[Citation] = Field(default_factory=list)
    intent: Literal["FACT", "FEE", "COMBINED"] | None = None
    scheme: str | None = None
    message: str | None = None  # refusal / not-found / clarifying text
    refusal_reason: str | None = None
    notices: list[str] = Field(default_factory=list)  # PII reminder, advice split, gaps
    links: list[str] = Field(default_factory=list)
    retrieved_chunk_ids: list[str] = Field(default_factory=list)
    cited_chunk_ids: list[str] = Field(default_factory=list)
    mode: str = "none"  # template | llm | extractive | none
    validation_errors: list[str] = Field(default_factory=list)
    last_updated: str | None = None
    latency_ms: int = 0


def _supported() -> str:
    return "; ".join(s.canonical for s in schemes())


def _official_link() -> str:
    return load_yaml("refusals.yaml")["education_links"][0]


# --- A-09: advice hidden inside a factual question ----------------------------------------
_CLAUSE = re.compile(
    r"(?<=[?.!])\s+|;\s*|,?\s+(?:and|but|also|or)\s+(?=(?:should|shall|can|could|would|will|"
    r"which|is it|do you|tell me which|recommend|suggest)\b)",
    re.I,
)


def split_advice(text: str) -> str | None:
    """Factual remainder of a message whose other clause asks for advice (None if none)."""
    clauses = [c.strip(" ,") for c in _CLAUSE.split(text) if c and c.strip(" ,")]
    if len(clauses) < 2:
        return None
    keep = [
        c
        for c in clauses
        if check_input(c, use_llm=False).intent in (Intent.ALLOWED, Intent.PII_SHARED)
    ]
    if not keep or len(keep) == len(clauses):
        return None
    rest = " ".join(keep)
    return rest if rest.endswith("?") else rest + "?"


# --- Main entry point ---------------------------------------------------------------------
def _citations(
    composed: comp.Composed, by_id: dict[str, Retrieved]
) -> tuple[list[Citation], list[list[int]]]:
    srcs = sources_by_id()
    order: dict[str, Citation] = {}
    per_bullet: list[list[int]] = []
    for ids in composed.bullet_cites:
        nums: list[int] = []
        for cid in ids:
            if cid not in by_id:
                continue
            doc = cid.split("#")[0]
            if doc not in order:
                s = srcs[doc]
                order[doc] = Citation(
                    n=len(order) + 1,
                    doc_id=doc,
                    title=s.short_title,
                    url=s.url,
                    source_type=s.source_type,
                    fetched_on=s.fetched_on,
                )
            c = order[doc]
            if cid not in c.chunk_ids:
                c.chunk_ids.append(cid)
            if c.n not in nums:
                nums.append(c.n)
        per_bullet.append(nums)
    return list(order.values()), per_bullet


def _compose(
    q: str, plan: RoutePlan, frame: comp.Frame | None, chunks: list[Retrieved], use_llm: bool
) -> tuple[comp.Composed | None, list[str]]:
    """Composer with validation; returns (answer, validation errors of the returned answer)."""
    grounding = frame.grounding if frame else set()

    def check(c: comp.Composed) -> list[str]:
        return validate(
            c, chunks, intent=plan.intent if frame else "FEE", question=q, grounding=grounding
        ).errors

    if use_llm:
        from core.llm import LLMError

        feedback: list[str] | None = None
        for _ in range(2):  # first try + one regeneration with the validator's errors
            try:
                cand = comp.llm_compose(q, frame, chunks, feedback)
            except LLMError as exc:
                _log.warning("kb_llm_compose_failed", extra={"error": str(exc)[:200]})
                break
            errors = check(cand)
            if not errors:
                return cand, []
            feedback = errors
            _log.info("kb_llm_validation_failed", extra={"errors": errors[:6]})

    if frame:
        cand = comp.template(frame)
    else:
        rerank = get_retriever().settings.rerank_enabled and not get_retriever().degraded
        cand = comp.extractive(
            q, chunks, rerank=rerank, min_score=get_settings().extractive_min_score
        )
        if cand is None:
            return None, []
    errors = check(cand)
    if errors:
        _log.warning("kb_template_validation", extra={"errors": errors[:6], "mode": cand.mode})
    return cand, errors


def answer(query: str, session_id: str | None = None, *, use_llm: bool | None = None) -> KBAnswer:
    """Answer a Unified Search question. Never raises for user input."""
    t0 = time.perf_counter()
    settings = get_settings()

    def done(ans: KBAnswer) -> KBAnswer:
        ans.latency_ms = int((time.perf_counter() - t0) * 1000)
        _log.info(
            "kb_answer",
            extra={
                "session_id": session_id,
                "status": ans.status,
                "intent": ans.intent,
                "mode": ans.mode,
                "latency_ms": ans.latency_ms,
                "query_chars": len(query or ""),
                "retrieved": ans.retrieved_chunk_ids,
                "cited": ans.cited_chunk_ids,
                "validation_errors": ans.validation_errors,
            },
        )
        return ans

    decision = check_input(query)
    notices = [decision.notice] if decision.notice else []
    q = decision.clean_text
    if decision.blocked:
        rest = split_advice(q) if decision.intent is Intent.ADVICE else None
        if rest is None:
            return done(
                KBAnswer(
                    status="REFUSED",
                    message=decision.refusal,
                    refusal_reason=decision.intent.value,
                    links=decision.links,
                    notices=notices,
                )
            )
        notices.append(
            "I can't advise on choosing or switching funds, but here are the facts "
            "you asked about. An advisor call can help with the decision."
        )
        q = rest

    plan = route(q)
    base = {
        "intent": plan.intent,
        "scheme": plan.scheme.canonical if plan.scheme else None,
        "notices": notices,
    }
    if plan.other_scheme:
        return done(
            KBAnswer(
                status="NOT_FOUND",
                refusal_reason="unsupported_scheme",
                message=f"“{plan.other_scheme}” is not in my sources. I cover: {_supported()}.",
                **base,
            )
        )
    if plan.needs_scheme:
        return done(
            KBAnswer(
                status="CLARIFY",
                refusal_reason="scheme_needed",
                message=f"Which scheme do you mean? I cover: {_supported()}.",
                **base,
            )
        )
    if plan.unknown_fee and not plan.fee_types and not plan.fields:
        return done(
            KBAnswer(
                status="NOT_FOUND",
                refusal_reason="fee_not_in_sources",
                message=refusal("not_in_sources", link=_official_link()),
                **base,
            )
        )
    if plan.unknown_fee:
        notices.append(
            f"{plan.unknown_fee.upper() if len(plan.unknown_fee) <= 4 else plan.unknown_fee} "
            "is not covered in my sources, so this answer covers the other charges."
        )
    try:
        retriever = get_retriever()
    except IndexNotBuilt:
        return done(
            KBAnswer(
                status="UNAVAILABLE",
                refusal_reason="index_not_built",
                message="The knowledge base index is not built yet. Rebuild it "
                "from the Unified Search tab.",
                **base,
            )
        )

    try:
        frame = comp.build_frame(plan)
    except LookupError as exc:
        _log.warning("kb_frame_failed", extra={"error": str(exc)})
        frame = None
    if plan.other_schemes:
        compared = 3 if frame and frame.topic.startswith("compare_") else 1
        rest = [plan.scheme, *plan.other_schemes][compared:]
        if rest:
            names = ", ".join(s.canonical for s in rest)
            notices.append(
                f"This answer covers {compared} scheme(s); ask separately about {names}."
            )
    chunks = retriever.retrieve(
        plan.sub_queries, plan.scheme, frame.pinned if frame else [], query=q
    )
    retrieved_ids = [c.chunk_id for c in chunks]
    if not chunks:
        return done(
            KBAnswer(
                status="NOT_FOUND",
                refusal_reason="below_relevance",
                message=refusal("not_in_sources", link=_official_link()),
                retrieved_chunk_ids=retrieved_ids,
                **base,
            )
        )

    llm_on = settings.rag_llm_enabled if use_llm is None else use_llm
    if llm_on:
        from core.llm import llm_available

        llm_on = llm_available()
    composed, errors = _compose(q, plan, frame, chunks, llm_on)
    if composed is None:
        return done(
            KBAnswer(
                status="NOT_FOUND",
                refusal_reason="no_answerable_text",
                message=refusal("not_in_sources", link=_official_link()),
                retrieved_chunk_ids=retrieved_ids,
                **base,
            )
        )

    out = check_output("\n".join(composed.bullets))
    if not out.ok:
        return done(
            KBAnswer(
                status="REFUSED",
                refusal_reason="output_guardrail",
                message=out.safe_text,
                retrieved_chunk_ids=retrieved_ids,
                validation_errors=out.violations,
                **base,
            )
        )

    by_id = {c.chunk_id: c for c in chunks}
    citations, per_bullet = _citations(composed, by_id)
    dates = [c.fetched_on for c in citations if c.fetched_on]
    if retriever.degraded:
        notices.append(
            "Search models are unavailable, so this answer uses the verified facts only."
        )
    status: Status = "PARTIAL" if plan.unknown_fee else "ANSWERED"
    return done(
        KBAnswer(
            status=status,
            bullets=composed.bullets,
            bullet_citations=per_bullet,
            citations=citations,
            retrieved_chunk_ids=retrieved_ids,
            cited_chunk_ids=list(dict.fromkeys(c for ids in composed.bullet_cites for c in ids)),
            mode=composed.mode,
            validation_errors=errors,
            last_updated=max(dates) if dates else None,
            **base,
        )
    )
