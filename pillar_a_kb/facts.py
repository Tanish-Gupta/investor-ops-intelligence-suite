"""Structured facts layer: scheme field extraction → `scheme_facts` (docs/architecture/rag.md §3).

Numbers in answers are looked up here, not generated. Every row keeps the exact source line
(`evidence`) so citations and number-grounding point at real text.

CLI:
    python -m pillar_a_kb.facts            # extract + upsert, print the spot-check table
    python -m pillar_a_kb.facts --verify   # after checking the table by hand, mark rows verified
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from datetime import date

from core import state
from pillar_a_kb.corpus import Document, fee_rules, load_documents, scheme_by_name, schemes

# label (lowercase, as on the page) -> field name
_LABELS: dict[str, str] = {
    "expense ratio": "expense_ratio",
    "exit load": "exit_load",
    "exit load detail": "exit_load_detail",
    "lock in": "lock_in",
    "lock-in period": "lock_in",
    "min lumpsum/sip": "min_investment",
    "benchmark": "benchmark",
    "risk": "riskometer",
}
FIELD_LABELS: dict[str, str] = {
    "expense_ratio": "Expense ratio",
    "exit_load": "Exit load",
    "lock_in": "Lock-in",
    "min_sip": "Minimum SIP",
    "min_lumpsum": "Minimum lump sum",
    "benchmark": "Benchmark",
    "riskometer": "Riskometer",
}
_LINE = re.compile(r"^\s*([A-Za-z][A-Za-z /-]+?)\s*·\s*(.+?)\s*$", re.M)
_DAY_LINE = re.compile(r"^Day (\d) · ([\d.]+%)$|^Day 7 onwards · NIL$", re.M)
_PCT = re.compile(r"(\d+(?:\.\d+)?)\s*%")


@dataclass(frozen=True)
class Fact:
    scheme_id: str
    scheme: str
    field: str
    value: str
    unit: str | None
    conditions: str | None
    evidence: str  # exact line(s) from the source document
    doc_id: str
    url: str
    as_of: date | None


def _as_of(raw: str) -> date | None:
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def _value_unit(field: str, raw: str) -> tuple[str, str | None]:
    if field in {"expense_ratio", "exit_load"} and (m := _PCT.search(raw)):
        return str(float(m.group(1))).rstrip("0").rstrip(".") or "0", "%"
    if field == "lock_in":
        if re.search(r"no lock-?in|^nil$", raw, re.I):
            return "0", "years"
        if m := re.search(r"(\d+)\s*year", raw, re.I):
            return m.group(1), "years"
    if field == "riskometer":
        return re.sub(r"^Risk meter pointer\s*", "", raw).removesuffix(" Risk"), None
    return raw, None


def extract_doc(doc: Document) -> list[Fact]:
    """Facts from one scheme capture (`F-*`)."""
    src = doc.source
    scheme = scheme_by_name(src.scheme)
    if scheme is None or src.source_type != "M1_FACTSHEET":
        return []
    common = dict(scheme_id=scheme.id, scheme=scheme.canonical, doc_id=src.doc_id, url=src.url)
    as_of = _as_of(src.as_of)
    facts: list[Fact] = []
    lines: dict[str, re.Match[str]] = {}
    for m in _LINE.finditer(doc.text):  # first occurrence of each label wins
        if (field := _LABELS.get(m.group(1).strip().lower())) and field not in lines:
            lines[field] = m
    detail = lines.pop("exit_load_detail", None)
    for field, m in lines.items():
        raw = m.group(2)
        evidence = m.group(0).strip()
        if field == "min_investment":
            lump, _, sip = raw.partition("/")
            for f, v in (("min_lumpsum", lump), ("min_sip", sip)):
                amount = re.sub(r"[^\d]", "", v)
                if not amount:  # page lists no value for this half (e.g. "–/₹1,000")
                    continue
                facts.append(
                    Fact(
                        **common,
                        field=f,
                        value=amount,
                        unit="INR",
                        conditions=None,
                        evidence=evidence,
                        as_of=as_of,
                    )
                )
            continue
        conditions = None
        if field == "exit_load":
            if detail:
                conditions, evidence = detail.group(2), f"{evidence}\n{detail.group(0).strip()}"
            elif "·" in raw:  # "1.0% · Exit load of 1%, if redeemed within 90 days."
                raw, conditions = (p.strip() for p in raw.split("·", 1))
        value, unit = _value_unit(field, raw)
        facts.append(
            Fact(
                **common,
                field=field,
                value=value,
                unit=unit,
                conditions=conditions,
                evidence=evidence,
                as_of=as_of,
            )
        )
    day_lines = [m.group(0) for m in _DAY_LINE.finditer(doc.text)]
    if day_lines:  # graded exit load table (liquid fund factsheet)
        facts = [f for f in facts if f.field != "exit_load"]
        facts.append(
            Fact(
                **common,
                field="exit_load",
                value="graded",
                unit="%",
                conditions="; ".join(day_lines),
                evidence="\n".join(day_lines),
                as_of=as_of,
            )
        )
    return facts


def extract_all() -> list[Fact]:
    return [f for doc in load_documents() for f in extract_doc(doc)]


def preferred_doc(scheme_id: str, field: str) -> str | None:
    """Doc that wins when two captures disagree (rule A5 / edge case A-06)."""
    if field == "exit_load":
        return fee_rules()["exit_load"]["schemes"][scheme_id]["doc_id"]
    return None


@dataclass(frozen=True)
class FactIndex:
    facts: tuple[Fact, ...]

    def get(self, scheme_id: str, field: str) -> Fact | None:
        rows = [f for f in self.facts if f.scheme_id == scheme_id and f.field == field]
        if not rows:
            return None
        if (pref := preferred_doc(scheme_id, field)) and (
            hit := [f for f in rows if f.doc_id == pref]
        ):
            return hit[0]
        order = {
            d: i for i, d in enumerate(next(s for s in schemes() if s.id == scheme_id).doc_ids)
        }
        return sorted(
            rows, key=lambda f: (-(f.as_of or date.min).toordinal(), order.get(f.doc_id, 9))
        )[0]


_index: FactIndex | None = None


def fact_index() -> FactIndex:
    global _index
    if _index is None:
        _index = FactIndex(tuple(extract_all()))
    return _index


def sync_to_db(facts: list[Fact] | None = None) -> int:
    """Upsert facts into SQLite `scheme_facts`. Changed values lose their human verification."""
    facts = facts if facts is not None else extract_all()
    for f in facts:
        existing = state.get_scheme_facts(f.scheme, f.field)
        prior = next((r for r in existing if r.source_doc_id == f.doc_id), None)
        same = prior is not None and (prior.value, prior.conditions) == (f.value, f.conditions)
        state.upsert_scheme_fact(
            state.SchemeFact(
                scheme=f.scheme,
                field=f.field,
                value=f.value,
                unit=f.unit,
                conditions=f.conditions,
                source_doc_id=f.doc_id,
                url=f.url,
                as_of=f.as_of,
                verified_by_human=bool(same and prior.verified_by_human),
            )
        )
    return len(facts)


def _main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--verify", action="store_true", help="mark all current rows human-verified")
    args = ap.parse_args()
    facts = extract_all()
    sync_to_db(facts)
    print(f"{'scheme':6} {'field':15} {'value':10} {'unit':6} {'doc':11} evidence")
    for f in facts:
        print(
            f"{f.scheme_id:6} {f.field:15} {f.value[:10]:10} {f.unit or '':6} {f.doc_id:11} "
            f"{f.evidence.splitlines()[0][:70]}"
        )
    if args.verify:
        for row in state.get_scheme_facts():
            row.verified_by_human = True
            state.upsert_scheme_fact(row)
        print(f"Marked {len(facts)} rows verified.")


if __name__ == "__main__":
    _main()
