"""Answer validator (docs/architecture/rag.md §4.4) — pure code, no LLM."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import Decimal

from core.guardrails import output_violations
from pillar_a_kb.composer import MAX_WORDS, N_BULLETS, Composed
from pillar_a_kb.retriever import Retrieved
from pillar_a_kb.textutil import numbers, word_count


@dataclass
class Validation:
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def validate(
    answer: Composed,
    retrieved: list[Retrieved],
    *,
    intent: str,
    question: str = "",
    grounding: Iterable[Decimal] = (),
    check_output: bool = True,
) -> Validation:
    v = Validation()
    by_id = {r.chunk_id: r for r in retrieved}
    b, cites = answer.bullets, answer.bullet_cites

    if len(b) != N_BULLETS:
        v.errors.append(f"bullet_count:{len(b)}")
    if len(cites) != len(b):
        v.errors.append("citation_list_length")
    for i, text in enumerate(b, 1):
        if word_count(text) > MAX_WORDS:
            v.errors.append(f"bullet_{i}_too_long:{word_count(text)}")
        if not text.strip():
            v.errors.append(f"bullet_{i}_empty")

    all_cited: set[str] = set()
    for i, ids in enumerate(cites, 1):
        if not ids:
            v.errors.append(f"bullet_{i}_uncited")
        bad = [c for c in ids if c not in by_id]
        if bad:
            v.errors.append(f"bullet_{i}_cites_unretrieved:{','.join(bad)}")
        all_cited.update(c for c in ids if c in by_id)

    if intent == "COMBINED":
        cited = [by_id[c] for c in all_cited]
        if not any(r.is_m1 for r in cited):
            v.errors.append("combined_missing_m1_source")
        if not any(r.is_m2 for r in cited):
            v.errors.append("combined_missing_m2_source")

    allowed = set(grounding) | numbers(question)
    for i, (text, ids) in enumerate(zip(b, cites, strict=False), 1):
        if i == N_BULLETS:  # sources line: dates and doc counts only
            continue
        pool = set(allowed)
        for c in ids:
            if c in by_id:
                pool |= numbers(by_id[c].text)
        missing = numbers(text) - pool
        if missing:
            shown = ",".join(sorted(format(m, "f") for m in missing))
            v.errors.append(f"bullet_{i}_ungrounded_numbers:{shown}")

    if check_output:
        for i, text in enumerate(b, 1):
            v.errors += [f"bullet_{i}_{p}" for p in output_violations(text)]
    return v
