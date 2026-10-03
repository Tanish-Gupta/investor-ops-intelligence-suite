"""Deterministic RAG checks on the golden set (Phase 3 smoke; Phase 8 adds the LLM judge).

Run: `uv run python -m evals.rag_checks` → prints a table and writes
`evals/reports/rag_checks.md` and `evals/reports/rag_checks.json`.

Per question (docs/evals.md §1.2, code-level part):
- structure: exactly 6 bullets, each ≤ 30 words
- coverage: cites every `required_source_types` (M1 and M2)
- citations ⊆ retrieved: no cited chunk outside the retrieved context
- number grounding: every number in bullets 1–5 is in a cited chunk, a fact or a calculator
- recall@k: share of `expected_doc_ids` present in the retrieved chunks
- evidence hit: share of the golden `evidence` quotes whose key numbers appear in the answer
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from pillar_a_kb.service import KBAnswer, answer
from pillar_a_kb.textutil import numbers, word_count

ROOT = Path(__file__).resolve().parent
GOLDEN = ROOT / "golden_dataset.json"
REPORTS = ROOT / "reports"

_M1 = ("M1_FACTSHEET", "M1_REGULATOR")


@dataclass
class ItemResult:
    id: str
    question: str
    status: str
    mode: str
    structure: bool
    coverage: bool
    citations_in_retrieved: bool
    grounded: bool
    recall_at_k: float
    evidence_hit: float
    latency_ms: int
    validation_errors: list[str] = field(default_factory=list)
    bullets: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return (
            self.status in ("ANSWERED", "PARTIAL")
            and self.structure
            and self.coverage
            and self.citations_in_retrieved
            and self.grounded
        )


def _source_kinds(ans: KBAnswer) -> set[str]:
    kinds = set()
    for c in ans.citations:
        kinds.add(
            "M1"
            if c.source_type in _M1
            else "M2"
            if c.source_type.startswith("M2")
            else c.source_type
        )
    return kinds


def _evidence_hit(item: dict, ans: KBAnswer) -> float:
    text = " ".join(ans.bullets)
    nums_in_answer = numbers(text)
    hits = 0
    for ev in item.get("evidence", []):
        ev_nums = numbers(ev["text"])
        if ev_nums:
            hits += bool(ev_nums & nums_in_answer)
        else:
            words = {w for w in re.findall(r"[a-z]{4,}", ev["text"].lower())}
            hits += len(words & set(re.findall(r"[a-z]{4,}", text.lower()))) >= len(words) / 2
    return hits / max(len(item.get("evidence", [])), 1)


def check_item(item: dict) -> ItemResult:
    ans = answer(item["question"], session_id=f"eval-{item['id']}", use_llm=False)
    return check_answer(item, ans)


def check_answer(item: dict, ans: KBAnswer) -> ItemResult:
    required = {"M1" if t.startswith("M1") else "M2" for t in item["required_source_types"]}
    retrieved_docs = {c.split("#")[0] for c in ans.retrieved_chunk_ids}
    expected = item.get("expected_doc_ids", [])
    return ItemResult(
        id=item["id"],
        question=item["question"],
        status=ans.status,
        mode=ans.mode,
        structure=len(ans.bullets) == 6 and all(word_count(b) <= 30 for b in ans.bullets),
        coverage=required <= _source_kinds(ans),
        citations_in_retrieved=set(ans.cited_chunk_ids) <= set(ans.retrieved_chunk_ids),
        grounded=not any("number" in e for e in ans.validation_errors),
        recall_at_k=sum(d in retrieved_docs for d in expected) / max(len(expected), 1),
        evidence_hit=round(_evidence_hit(item, ans), 2),
        latency_ms=ans.latency_ms,
        validation_errors=ans.validation_errors,
        bullets=ans.bullets,
    )


def run(path: Path = GOLDEN) -> list[ItemResult]:
    items = json.loads(path.read_text(encoding="utf-8"))
    return [check_item(it) for it in items]


def _mark(ok: bool) -> str:
    return "✅" if ok else "❌"


def to_markdown(results: list[ItemResult]) -> str:
    when = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# RAG code checks — golden set",
        "",
        f"Run: {when}. Composer: deterministic (no LLM). LLM-judged Faithfulness/Relevance "
        "are added in Phase 8.",
        "",
        "| ID | Status | Mode | 6 bullets | M1+M2 | Cites ⊆ retrieved | Numbers grounded "
        "| Recall@k | Evidence hit | Latency |",
        "|----|--------|------|-----------|-------|-------------------|------------------"
        "|----------|--------------|---------|",
    ]
    for r in results:
        lines.append(
            f"| {r.id} | {r.status} | {r.mode} | {_mark(r.structure)} | {_mark(r.coverage)} | "
            f"{_mark(r.citations_in_retrieved)} | {_mark(r.grounded)} | {r.recall_at_k:.2f} | "
            f"{r.evidence_hit:.2f} | {r.latency_ms} ms |"
        )
    passed = sum(r.passed for r in results)
    recall = sum(r.recall_at_k for r in results) / max(len(results), 1)
    lines += ["", f"**Passed:** {passed}/{len(results)} · **Mean recall@k:** {recall:.2f}", ""]
    for r in results:
        lines += [f"## {r.id} — {r.question}", ""]
        lines += [f"{i}. {b}" for i, b in enumerate(r.bullets, 1)]
        if r.validation_errors:
            lines += ["", "Validation errors: " + "; ".join(r.validation_errors)]
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    results = run()
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "rag_checks.md").write_text(to_markdown(results), encoding="utf-8")
    (REPORTS / "rag_checks.json").write_text(
        json.dumps(
            [asdict(r) | {"passed": r.passed} for r in results], indent=2, ensure_ascii=False
        ),
        encoding="utf-8",
    )
    for r in results:
        print(
            f"{r.id}: {'PASS' if r.passed else 'FAIL'} status={r.status} "
            f"recall={r.recall_at_k:.2f} evidence={r.evidence_hit:.2f} {r.latency_ms}ms"
        )
    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
