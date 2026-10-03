"""Eval 1 — Retrieval accuracy (RAG) on the golden set G1–G5 (docs/evals.md §1).

Faithfulness (per item, 0–1): claims = bullets 1–5. A claim is supported when its citations are
inside the retrieved set, every number in it is grounded (cited chunk, verified fact or
calculator), and at least half of its content words appear in the cited chunks. With the opt-in
LLM judge, claim extraction + verification is done by the judge instead. Hard caps: an invented
citation or an ungrounded number caps the item at 0.5.

Relevance (per item, 0–1) = mean of answers_fact (M1 evidence found in the answer),
answers_fee_scenario (M2 evidence found) and on_topic (combined intent, answered in 6 bullets).
The judge replaces these three sub-scores when enabled.
"""

from __future__ import annotations

import json
import re
import time

from evals import judge
from evals.common import Check, Metric, SuiteResult, ratio
from evals.rag_checks import GOLDEN, _evidence_hit, check_answer
from pillar_a_kb.service import KBAnswer, answer

N_CLAIMS = 5  # bullet 6 is the sources line
SUPPORT_MIN = 0.5
FAITH_AVG, FAITH_MIN, RELEVANCE_AVG = 0.90, 0.75, 0.80

_STOP = set(
    "the a an and or of to in on for is are was be this that with your you it as at by from if "
    "not no any can may per its after before only which what why how so than then there their "
    "gives get got".split()
)


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", text.lower()) if len(w) > 2 and w not in _STOP}


def _chunk_texts(ids: list[str]) -> dict[str, str]:
    from pillar_a_kb.retriever import get_retriever

    try:
        return {r.chunk_id: r.text for r in get_retriever().by_ids(ids)}
    except Exception:  # index missing → support falls back to 0 and the item fails visibly
        return {}


def _bullet_chunks(ans: KBAnswer) -> list[list[str]]:
    by_n = {c.n: c.chunk_ids for c in ans.citations}
    return [[cid for n in ns for cid in by_n.get(n, [])] for ns in ans.bullet_citations]


def faithfulness(item: dict, ans: KBAnswer) -> tuple[float, dict]:
    per_bullet = _bullet_chunks(ans)
    texts = _chunk_texts(sorted({c for ids in per_bullet for c in ids}))
    retrieved = set(ans.retrieved_chunk_ids)
    invented = not set(ans.cited_chunk_ids) <= retrieved
    ungrounded = {
        int(m.group(1))
        for e in ans.validation_errors
        if (m := re.match(r"bullet_(\d+)_ungrounded_numbers", e))
    }
    claims = []
    for i, (bullet, ids) in enumerate(zip(ans.bullets[:N_CLAIMS], per_bullet, strict=False), 1):
        src = " ".join(texts.get(c, "") for c in ids)
        words = _words(bullet)
        support = len(words & _words(src)) / max(len(words), 1)
        ok = bool(ids) and set(ids) <= retrieved and i not in ungrounded and support >= SUPPORT_MIN
        claims.append({"bullet": i, "support": round(support, 2), "supported": ok})
    score = sum(c["supported"] for c in claims) / N_CLAIMS if claims else 0.0
    method = "proxy"
    verdict = judge.faithfulness(item["question"], ans.bullets, list(texts.values()))
    if verdict is not None:
        score, method = verdict.score, "judge"
        claims = [c.model_dump() for c in verdict.claims]
    if invented or ungrounded:
        score = min(score, 0.5)
    return round(score, 3), {
        "method": method,
        "claims": claims,
        "invented_citation": invented,
        "ungrounded_bullets": sorted(ungrounded),
    }


def _hit(item: dict, ans: KBAnswer, prefix: str) -> float:
    ev = [e for e in item.get("evidence", []) if e["doc_id"].startswith(prefix)]
    return _evidence_hit({"evidence": ev}, ans) if ev else 1.0


def relevance(item: dict, ans: KBAnswer) -> tuple[float, dict]:
    answered = ans.status in ("ANSWERED", "PARTIAL") and len(ans.bullets) == 6
    on_topic = float(answered and ans.intent == item.get("expected_intent", ans.intent))
    parts: dict = {
        "answers_fact": round(_hit(item, ans, "F-"), 2) if answered else 0.0,
        "answers_fee_scenario": round(_hit(item, ans, "FE-"), 2) if answered else 0.0,
        "on_topic": on_topic,
    }
    method = "proxy"
    verdict = judge.relevance(item["question"], ans.bullets, item) if answered else None
    if verdict is not None:
        parts = verdict.model_dump()
        method = "judge"
    score = (parts["answers_fact"] + parts["answers_fee_scenario"] + parts["on_topic"]) / 3
    return round(score, 3), parts | {"method": method}


def run() -> SuiteResult:
    res = SuiteResult("rag", "Retrieval accuracy (RAG)")
    items = json.loads(GOLDEN.read_text(encoding="utf-8"))
    faith: list[float] = []
    rel: list[float] = []
    recall: list[float] = []
    struct = cover = 0
    for item in items:
        t0 = time.perf_counter()
        ans = answer(item["question"], session_id=f"eval-{item['id']}")
        code = check_answer(item, ans)
        f, f_data = faithfulness(item, ans)
        r, r_data = relevance(item, ans)
        faith.append(f)
        rel.append(r)
        struct += code.structure
        cover += code.coverage
        recall.append(code.recall_at_k)
        res.checks.append(
            Check(
                id=item["id"],
                name=item["question"],
                passed=code.passed and f >= FAITH_MIN and r >= RELEVANCE_AVG,
                score=f,
                detail=f"faith {f:.2f} · rel {r:.2f} · {ans.status}/{ans.mode} · "
                f"recall@k {code.recall_at_k:.2f}",
                data={
                    "faithfulness": f,
                    "relevance": r,
                    "status": ans.status,
                    "mode": ans.mode,
                    "intent": ans.intent,
                    "structure": code.structure,
                    "coverage": code.coverage,
                    "citations_in_retrieved": code.citations_in_retrieved,
                    "grounded": code.grounded,
                    "recall_at_k": code.recall_at_k,
                    "evidence_hit": code.evidence_hit,
                    "latency_ms": int((time.perf_counter() - t0) * 1000),
                    "faithfulness_detail": f_data,
                    "relevance_detail": r_data,
                    "bullets": ans.bullets,
                    "sources": [f"[{c.n}] {c.title} — {c.url}" for c in ans.citations],
                    "validation_errors": ans.validation_errors,
                },
            )
        )
    n = len(items)
    avg_f = sum(faith) / n if n else 0.0
    avg_r = sum(rel) / n if n else 0.0
    min_f = min(faith, default=0.0)
    res.metrics = [
        Metric("Faithfulness (avg)", f"{avg_f:.2f}", f"≥ {FAITH_AVG:.2f}", avg_f >= FAITH_AVG),
        Metric("Faithfulness (min item)", f"{min_f:.2f}", f"≥ {FAITH_MIN:.2f}", min_f >= FAITH_MIN),
        Metric("Relevance (avg)", f"{avg_r:.2f}", f"≥ {RELEVANCE_AVG:.2f}", avg_r >= RELEVANCE_AVG),
        Metric("6-bullet structure", ratio(struct, n), f"{n}/{n}", n > 0 and struct == n),
        Metric("Source coverage (M1+M2)", ratio(cover, n), f"{n}/{n}", n > 0 and cover == n),
    ]
    res.notes.append(f"Judge: {judge.judge_label()}. Mean recall@k {sum(recall) / max(n, 1):.2f}.")
    return res
