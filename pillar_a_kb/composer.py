"""Answer composer: the 6-bullet structure (docs/architecture/rag.md §4.3).

A deterministic *answer frame* is built before retrieval from the router plan, the
`scheme_facts` index and the fee calculators. It holds the template bullets with per-bullet
citations and the chunk ids that must be pinned in the retrieved context. Every number in
it comes from a source line or a calculator, never from a model.

When an LLM is configured, `llm_compose` may rephrase the frame for the user's wording using
the retrieved context. Its output is checked by the validator and falls back to the template.
Questions the frame cannot place (open questions) use `extractive`: the best-matching
sentences of the top retrieved chunks, each cited.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field

from pillar_a_kb import calculators as calc
from pillar_a_kb.corpus import Scheme, explainer_parts, fee_rules, sources_by_id
from pillar_a_kb.facts import Fact, fact_index
from pillar_a_kb.retriever import Retrieved
from pillar_a_kb.router import RoutePlan
from pillar_a_kb.textutil import first_sentences, numbers, trim_words, word_count

_log = logging.getLogger(__name__)

N_BULLETS = 6
MAX_WORDS = 30

FEE_LABELS = {
    "FE-EXIT-01": "Exit load",
    "FE-GRADED-01": "Graded exit load",
    "FE-STAMP-01": "Stamp duty",
    "FE-STT-01": "STT",
    "FE-TER-01": "Expense ratio (TER)",
    "FE-LOCKIN-01": "ELSS lock-in",
    "FE-CG-01": "Account statement",
}
FIELD_LABELS = {
    "exit_load": "exit load",
    "expense_ratio": "expense ratio",
    "lock_in": "lock-in",
    "min_investment": "minimum investment",
    "benchmark": "benchmark",
    "riskometer": "riskometer level",
}
_FEE_DOC = {
    "exit_load": "FE-EXIT-01",
    "stamp_duty": "FE-STAMP-01",
    "stt": "FE-STT-01",
    "expense_ratio": "FE-TER-01",
    "lock_in": "FE-LOCKIN-01",
    "capital_gains": "FE-CG-01",
}


@dataclass
class Bullet:
    text: str
    cites: list[str]  # chunk ids


@dataclass
class Frame:
    """Deterministic answer draft for a routed question (bullets 1–5; bullet 6 is added later)."""

    topic: str
    bullets: list[Bullet]
    pinned: list[str]
    grounding: set[Decimal] = field(default_factory=set)  # numbers from facts and calculators
    premise: str | None = None  # note when the question's premise is corrected


@dataclass
class Composed:
    bullets: list[str]
    bullet_cites: list[list[str]]  # chunk ids per bullet
    mode: str  # template | llm | extractive


# --- Helpers ------------------------------------------------------------------------------
def card_id(f: Fact) -> str:
    fld = "min_investment" if f.field in ("min_sip", "min_lumpsum") else f.field
    return f"{f.doc_id}#{fld}"


def _fact(scheme: Scheme, fld: str) -> Fact | None:
    return fact_index().get(scheme.id, "min_sip" if fld == "min_investment" else fld)


def _evidence(f: Fact) -> str:
    text = "; ".join(line.strip() for line in f.evidence.splitlines() if line.strip())
    return text.rstrip(". ")


def _name(scheme: Scheme) -> str:
    return f"the {scheme.canonical}"  # keep the AMC: both AMCs have e.g. a Flexi Cap Fund


def _src(f: Fact) -> str:
    """How a bullet names the fact's source document."""
    title = sources_by_id().get(f.doc_id)
    return "Factsheet" if title and "factsheet" in title.title.lower() else "Scheme page"


def _graded(s: Scheme) -> bool:
    return bool(fee_rules()["exit_load"]["schemes"][s.id].get("graded"))


def _window_adj(label: str) -> str:
    """ "90 days" -> "90-day", "6 months" -> "6-month"."""
    m = re.fullmatch(r"(\d+) (day|month|year)s?", label)
    return f"{m.group(1)}-{m.group(2)}" if m else label


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:]


def _part(doc_id: str, key: str, limit: int = MAX_WORDS) -> str:
    return first_sentences(explainer_parts(doc_id).get(key, ""), limit)


_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z₹(\"])")


def _sents(doc_id: str, key: str, start: int, stop: int | None = None) -> str:
    """Sentences [start:stop] of an explainer part, trimmed to the bullet limit."""
    parts = _SPLIT.split(explainer_parts(doc_id).get(key, ""))
    return trim_words(" ".join(parts[start:stop]), MAX_WORDS)


def _rate(key: str) -> str:
    return str(fee_rules()[key]["rate_pct"])


def _days(n: int) -> str:
    return f"{n} day" + ("" if n == 1 else "s")


def _held(plan: RoutePlan) -> str:
    sc = plan.scenario
    return sc.holding_text or _days(sc.holding_days or 0)


def _other_charges(category: str) -> tuple[str, list[str]]:
    """Sentence naming the charges that explain a smaller credit when no exit load applies."""
    duty = calc.inr(Decimal("10000") * calc.pct(_rate("stamp_duty")))
    text = (
        f"A deduction is more likely stamp duty ({_rate('stamp_duty')}% on purchase, e.g. "
        f"{duty} on ₹10,000)"
    )
    cites = ["FE-STAMP-01"]
    if calc.stt_applies(category):
        text += f" or STT ({_rate('stt')}% on equity-fund redemption)"
        cites.append("FE-STT-01")
    return text + ".", cites


# --- Topic frames -------------------------------------------------------------------------
def _exit_load_frame(plan: RoutePlan, s: Scheme) -> Frame:
    sc = plan.scenario
    el = calc.exit_load(s.id, sc.holding_days, sc.amount)
    f_el = _fact(s, "exit_load")
    f_lock = _fact(s, "lock_in")
    if f_el is None:
        raise LookupError(f"no exit_load fact for {s.id}")
    cards = [card_id(f_el)] + ([card_id(f_lock)] if f_lock and not _graded(s) else [])
    b: list[Bullet] = []
    grounding = set(el.calc.numbers)
    premise = None
    name = _name(s)

    if el.status == "no_load":
        lock = f_lock.value if f_lock else "0"
        if lock != "0":
            b.append(
                Bullet(
                    f"{_cap(name)} has no exit load (0%); instead, units are locked in "
                    f"for {lock} years from allotment.",
                    cards,
                )
            )
        else:
            b.append(
                Bullet(
                    f"{_cap(name)} has no exit load (0%), so redeeming units at any time "
                    "does not attract an exit load.",
                    cards,
                )
            )
        b.append(
            Bullet(
                f"Scheme page: {_evidence(f_el)}" + (f"; {_evidence(f_lock)}." if f_lock else "."),
                cards,
            )
        )
        if s.category == "ELSS":
            b.append(
                Bullet(
                    "An exit load applies only to units redeemed inside a scheme's "
                    "exit-load period; ELSS units cannot be redeemed during the lock-in.",
                    ["FE-EXIT-01", "FE-LOCKIN-01"],
                )
            )
        else:
            b.append(Bullet(_part("FE-EXIT-01", "why", 22), ["FE-EXIT-01"]))
        text, cites = _other_charges(s.category)
        grounding |= numbers(text)
        b.append(Bullet(text, cites))
        b.append(
            Bullet(
                "Check your account statement: match the deduction to a purchase (stamp "
                "duty) or a redemption (STT) and its date.",
                ["FE-CG-01"],
            )
        )
        if plan.asks_why:
            premise = f"{s.canonical} has a 0% exit load, so the deduction is not an exit load."
        pinned = [*cards, "FE-EXIT-01", *b[2].cites, *cites, "FE-CG-01"]
        return Frame("exit_load", b, pinned, grounding, premise)

    if el.status in ("graded", "graded_nil", "unknown_period") and _graded(s):
        rules = fee_rules()["exit_load"]["schemes"][s.id]
        slabs = rules["slabs"]
        nil = rules["nil_from_day"]
        if el.status == "graded":
            b.append(
                Bullet(
                    f"Redeeming on day {sc.holding_days} triggers {name}'s graded exit "
                    f"load of {el.rate_pct}% of the redemption proceeds.",
                    cards,
                )
            )
        elif el.status == "graded_nil":
            b.append(
                Bullet(
                    f"No exit load applies: you redeemed on day {sc.holding_days}, and "
                    f"{name}'s graded exit load is nil from day {nil}.",
                    cards,
                )
            )
        else:
            b.append(
                Bullet(
                    f"{_cap(name)} has a graded exit load for redemptions in the first "
                    f"{nil - 1} days, from {slabs[0]['rate_pct']}% on day 1 to "
                    f"{slabs[-1]['rate_pct']}% on day {slabs[-1]['day']}; nil from day "
                    f"{nil}.",
                    cards,
                )
            )
        b.append(
            Bullet(
                f"{_src(f_el)} slabs: day 1 {slabs[0]['rate_pct']}%, day 3 "
                f"{slabs[2]['rate_pct']}%, day {slabs[-1]['day']} "
                f"{slabs[-1]['rate_pct']}%; nil from day {nil}.",
                cards,
            )
        )
        b.append(
            Bullet(
                _sents("FE-GRADED-01", "why", 1)
                if plan.asks_why
                else _sents("FE-GRADED-01", "what", 0, 2),
                ["FE-GRADED-01"],
            )
        )
        b.append(Bullet(el.calc.text, ["FE-GRADED-01", *cards]))
        b.append(
            Bullet(
                "Check your purchase and redemption dates on the statement to confirm "
                "the day count.",
                ["FE-GRADED-01", "FE-CG-01"],
            )
        )
        grounding |= {Decimal(str(sl["rate_pct"])).normalize() for sl in slabs}
        if plan.asks_why:
            premise = "Summary pages may show 0% for the liquid fund; the graded slabs still apply."
        return Frame("exit_load", b, [*cards, "FE-GRADED-01", "FE-CG-01"], grounding, premise)

    window, rate, label, free = el.window_days, el.rate_pct, el.window_label, el.free_units_pct
    adj = _window_adj(label)
    if el.status == "outside":
        b.append(
            Bullet(
                f"No exit load applies: you redeemed after {_held(plan)}, past "
                f"{name}'s {adj} exit-load window.",
                cards,
            )
        )
        if plan.asks_why:
            premise = f"Held past the {adj} window, so no exit load applies."
    elif el.status == "inside":
        applies = f"applies to units beyond the free {free}%" if free else "applies"
        b.append(
            Bullet(
                f"A {rate}% exit load {applies}: you redeemed after {_held(plan)}, "
                f"inside {name}'s {adj} exit-load window.",
                cards,
            )
        )
    else:
        units = f"units beyond the first {free}%" if free else "units"
        b.append(
            Bullet(
                f"{_cap(name)} charges a {rate}% exit load on {units} redeemed within "
                f"{label} of allotment; after that there is none.",
                cards,
            )
        )
    b.append(
        Bullet(
            f"Scheme page: {_evidence(f_el)}" + (f"; {_evidence(f_lock)}." if f_lock else "."),
            cards,
        )
    )
    b.append(Bullet(_part("FE-EXIT-01", "how", 25), ["FE-EXIT-01"]))
    b.append(Bullet(el.calc.text, ["FE-EXIT-01", *cards]))
    check = "Check the purchase date of each lot on your statement"
    cites = ["FE-CG-01"]
    if calc.stt_applies(s.category):
        check += f"; a small deduction on redemption may be STT ({_rate('stt')}%)."
        cites.append("FE-STT-01")
    else:
        check += "."
    b.append(Bullet(check, cites))
    grounding.add(Decimal(str(window)))
    grounding |= numbers(label) | ({Decimal(free)} if free else set())
    return Frame("exit_load", b, [*cards, "FE-EXIT-01", *cites], grounding, premise)


def _ter_frame(plan: RoutePlan, s: Scheme) -> Frame:
    f = _fact(s, "expense_ratio")
    if f is None:
        raise LookupError(f"no expense_ratio fact for {s.id}")
    c = calc.expense_ratio(f.value)
    cards = [card_id(f)]
    b = [
        Bullet(
            f"{_cap(name := _name(s))} has an expense ratio of {f.value}% a year, deducted "
            "inside the NAV, not charged separately to your bank account.",
            [*cards, "FE-TER-01"],
        ),
        Bullet(
            f"Factsheet: {_evidence(f)}."
            if _src(f) == "Factsheet"
            else f"Scheme page: {_evidence(f)} for {name}'s direct growth plan.",
            cards,
        ),
        Bullet(_sents("FE-TER-01", "how", 1, 2), ["FE-TER-01"]),
        Bullet(c.text, ["FE-TER-01", *cards]),
        Bullet(
            "Check the latest monthly factsheet for the current TER; there is no separate "
            "TER line on your statement.",
            ["FE-TER-01"],
        ),
    ]
    return Frame("expense_ratio", b, [*cards, "FE-TER-01"], set(c.numbers))


def _stamp_frame(plan: RoutePlan, s: Scheme | None) -> Frame:
    sc = plan.scenario
    amt = sc.amount or Decimal("10000")
    c = calc.stamp_duty(amt)
    duty = amt * calc.pct(_rate("stamp_duty"))
    b: list[Bullet] = []
    pinned = ["FE-STAMP-01"]
    f = _fact(s, "min_investment") if s and "min_investment" in plan.fields else None
    if f:
        cards = [card_id(f)]
        pinned += cards
        diff = (
            f"; the {calc.inr(duty)} difference is stamp duty on your instalment."
            if len(sc.amounts) > 1
            else "; each SIP instalment also pays a small stamp duty."
        )
        b.append(
            Bullet(f"{_cap(_name(s))}'s minimum SIP is ₹{f.value}{diff}", [*cards, "FE-STAMP-01"])
        )
        b.append(
            Bullet(
                f"Scheme page: {_evidence(f)} (minimum lump sum / SIP) for the direct growth plan.",
                cards,
            )
        )
    else:
        b.append(
            Bullet(
                f"Stamp duty of {_rate('stamp_duty')}% is deducted from every mutual "
                "fund purchase, including each SIP instalment, before units are "
                "allotted.",
                ["FE-STAMP-01"],
            )
        )
        b.append(Bullet(_sents("FE-STAMP-01", "what", 1), ["FE-STAMP-01"]))
    b.append(Bullet(_part("FE-STAMP-01", "how"), ["FE-STAMP-01"]))
    b.append(Bullet(c.text, ["FE-STAMP-01"]))
    b.append(
        Bullet(
            "Check each purchase on your statement; the same small deduction appears on "
            "every SIP instalment.",
            ["FE-STAMP-01", "FE-CG-01"],
        )
    )
    pinned.append("FE-CG-01")
    return Frame("stamp_duty", b, pinned, set(c.numbers) | {duty.normalize()})


def _stt_frame(plan: RoutePlan, s: Scheme | None) -> Frame:
    amt = plan.scenario.amount or calc.EXAMPLE_AMOUNT
    c = calc.stt(amt)
    rate = _rate("stt")
    if s and not calc.stt_applies(s.category):
        first = f"{_cap(_name(s))} is a debt-oriented fund, so its redemptions do not attract STT."
    elif s:
        first = (
            f"STT of {rate}% is deducted when you redeem units of {_name(s)}, an equity-"
            "oriented fund."
        )
    else:
        first = (
            f"STT of {rate}% is deducted when you redeem units of equity-oriented mutual "
            "funds; debt funds do not attract it."
        )
    b = [
        Bullet(first, ["FE-STT-01"]),
        Bullet(_sents("FE-STT-01", "what", 1), ["FE-STT-01"]),
        Bullet(_part("FE-STT-01", "how"), ["FE-STT-01"]),
        Bullet(c.text, ["FE-STT-01"]),
        Bullet(
            "Check the redemption entry on your statement; STT is small and separate from "
            "any exit load.",
            ["FE-STT-01", "FE-CG-01"],
        ),
    ]
    return Frame("stt", b, ["FE-STT-01", "FE-CG-01"], set(c.numbers))


def _lock_in_frame(plan: RoutePlan, s: Scheme | None) -> Frame:
    f = _fact(s, "lock_in") if s else None
    if s and f and f.value == "0":
        cards = [card_id(f)]
        b = [
            Bullet(f"{_cap(_name(s))} has no lock-in; units can be redeemed at any time.", cards),
            Bullet(f"Scheme page: {_evidence(f)}.", cards),
            Bullet(_part("FE-LOCKIN-01", "what", 25), ["FE-LOCKIN-01"]),
            Bullet(_part("FE-LOCKIN-01", "how", 25), ["FE-LOCKIN-01"]),
            Bullet(
                "Check the scheme's exit-load period on the factsheet; an early redemption may "
                "still attract an exit load.",
                ["FE-EXIT-01"],
            ),
        ]
        return Frame("lock_in", b, [*cards, "FE-LOCKIN-01", "FE-EXIT-01"])
    c = calc.elss_lock_in()
    years = fee_rules()["lock_in"]["ELSS"]["years"]
    cards = [card_id(f)] if f else []
    b = [
        Bullet(
            f"ELSS units are locked in for {years} years from allotment; each SIP instalment "
            f"has its own {years}-year lock-in.",
            [*cards, "FE-LOCKIN-01"],
        ),
        Bullet(
            f"Scheme page: {_evidence(f)}." if f else _sents("FE-LOCKIN-01", "what", 1),
            cards or ["FE-LOCKIN-01"],
        ),
        Bullet(_part("FE-LOCKIN-01", "how", 30), ["FE-LOCKIN-01"]),
        Bullet(c.text, ["FE-LOCKIN-01"]),
        Bullet(
            "Check the allotment date of each instalment on your statement to see when it unlocks.",
            ["FE-LOCKIN-01", "FE-CG-01"],
        ),
    ]
    return Frame("lock_in", b, [*cards, "FE-LOCKIN-01", "FE-CG-01"], set(c.numbers))


def _concept_frame(fee: str) -> Frame:
    """General explanation of a fee type (no scheme named)."""
    doc = _FEE_DOC[fee]
    parts = explainer_parts(doc)
    b = [
        Bullet(_sents(doc, "what", 0, 1), [doc]),
        Bullet(_sents(doc, "what", 1), [doc]),
        Bullet(first_sentences(parts.get("how", ""), MAX_WORDS), [doc]),
        Bullet(first_sentences(parts.get("example", ""), MAX_WORDS), [doc]),
        Bullet(first_sentences(parts.get("why", ""), MAX_WORDS), [doc]),
    ]
    if fee in ("exit_load", "expense_ratio", "lock_in"):
        b[1] = _all_schemes_bullet(fee)
    pinned = list(dict.fromkeys(c for x in b for c in x.cites))
    return Frame(fee, b, pinned)


_SHORT = {
    "ELSS": "ELSS",
    "FLEXI": "Flexi Cap",
    "LC": "Large Cap",
    "IDX": "Nifty 50 Index",
    "LIQ": "Liquid",
}


def _short(s: Scheme) -> str:
    return _SHORT.get(s.id) or s.canonical.removesuffix(" Fund")


def _short_value(s: Scheme, fld: str) -> str | None:
    """Compact value of a field for side-by-side lists ("1% within 90 days", "0.67%")."""
    f = _fact(s, fld)
    if f is None:
        return None
    if fld == "exit_load":
        el = calc.exit_load(s.id)
        if el.status == "no_load":
            return "0%"
        if fee_rules()["exit_load"]["schemes"][s.id].get("graded"):
            return "graded (days 1–6)"
        return f"{el.rate_pct}% within {el.window_label}"
    if fld == "lock_in":
        return "no lock-in" if f.value == "0" else f"{f.value}-year lock-in"
    if fld == "min_investment":
        return f"₹{f.value}"
    return f"{f.value}%" if f.unit == "%" else f.value


def _all_schemes_bullet(fld: str) -> Bullet:
    from pillar_a_kb.corpus import schemes

    vals, cards = [], []
    for s in schemes():  # the M1 headline schemes; the full list would break the word limit
        if s.id not in _SHORT:
            continue
        v, f = _short_value(s, fld), _fact(s, fld)
        if v and f:
            vals.append(f"{_short(s)} {v}")
            cards.append(card_id(f))
    return Bullet("Scheme values: " + ", ".join(vals) + ".", cards)


def _compare_frame(plan: RoutePlan, fld: str) -> Frame | None:
    """Side-by-side answer for up to three named schemes on one field."""
    assert plan.scheme is not None
    group = [plan.scheme, *plan.other_schemes][:3]
    facts = [(s, f) for s in group if (f := _fact(s, fld))]
    if len(facts) < 2:
        return None
    label = "minimum SIP" if fld == "min_investment" else FIELD_LABELS[fld]
    cards = [card_id(f) for _, f in facts]
    summary = "; ".join(f"{_short(s)} {_short_value(s, fld)}" for s, _ in facts)
    b = [Bullet(f"{_cap(label)}: {summary}.", cards)]
    b += [Bullet(f"{_short(s)} scheme page: {_evidence(f)}.", [card_id(f)]) for s, f in facts]
    if doc := _FEE_DOC.get(fld):
        b += [
            Bullet(_sents(doc, "what", 0, 1), [doc]),
            Bullet(_part(doc, "how", 25), [doc]),
            Bullet(_part(doc, "why", 25), [doc]),
        ]
    else:
        for alt in ("expense_ratio", "riskometer", "benchmark", "min_investment"):
            alt_facts = [(s, _fact(s, alt)) for s, _ in facts]
            if alt == fld or not all(f for _, f in alt_facts):
                continue
            alt_label = "minimum SIP" if alt == "min_investment" else FIELD_LABELS[alt]
            b.append(
                Bullet(
                    f"{_cap(alt_label)}: "
                    + "; ".join(f"{_short(s)} {_short_value(s, alt)}" for s, _ in alt_facts)
                    + ".",
                    [card_id(f) for _, f in alt_facts if f],
                )
            )
    b = b[:5]
    pinned = list(dict.fromkeys(c for x in b for c in x.cites))
    return Frame(f"compare_{fld}", b, pinned)


def _fact_only_frame(plan: RoutePlan, s: Scheme) -> Frame:
    """A scheme snapshot answering a non-fee field (benchmark, riskometer, minimum)."""
    asked = [f for f in plan.fields if f in ("min_investment", "benchmark", "riskometer")]
    main = asked[0] if asked else "benchmark"
    order = [main] + [
        f
        for f in (
            "expense_ratio",
            "exit_load",
            "lock_in",
            "min_investment",
            "riskometer",
            "benchmark",
        )
        if f != main
    ]
    facts = [(fld, f) for fld in order if (f := _fact(s, fld))]
    first_fld, first = facts[0]
    value = f"₹{first.value}" if first.unit == "INR" else first.value
    label = "minimum SIP" if first_fld == "min_investment" else FIELD_LABELS[first_fld]
    b = [
        Bullet(f"{_cap(_name(s))}'s {label} is {value}.", [card_id(first)]),
        Bullet(f"Scheme page: {_evidence(first)}.", [card_id(first)]),
    ]
    for fld, f in facts[1:4]:
        b.append(
            Bullet(f"Its {FIELD_LABELS[fld]} on the scheme page: {_evidence(f)}.", [card_id(f)])
        )
    pinned = list(dict.fromkeys(c for x in b for c in x.cites))
    return Frame(main, b[:5], pinned)


def build_frame(plan: RoutePlan) -> Frame | None:
    """Template answer for routed questions; None when the plan names no field or fee."""
    s = plan.scheme
    fees, fields = plan.fee_types, plan.fields
    topics = fees + [f for f in fields if f not in fees]
    if not topics or plan.open_ended:
        return None
    if s is None:
        fee = next((f for f in topics if f in _FEE_DOC), None)
        return _concept_frame(fee) if fee else None
    if plan.other_schemes and "stamp_duty" not in fees:
        fld = next((t for t in topics if t in FIELD_LABELS), None)
        if fld and (fr := _compare_frame(plan, fld)):
            return fr
    if "stamp_duty" in fees:
        return _stamp_frame(plan, s)
    top = topics[0]
    if top == "exit_load":
        return _exit_load_frame(plan, s)
    if top == "expense_ratio":
        return _ter_frame(plan, s)
    if top == "lock_in":
        return _lock_in_frame(plan, s)
    if top == "stt":
        return _stt_frame(plan, s)
    if top == "capital_gains":
        return _concept_frame("capital_gains")
    return _fact_only_frame(plan, s)


# --- Bullet 6 and finalising --------------------------------------------------------------
def sources_bullet(chunk_ids: list[str]) -> str:
    srcs = sources_by_id()
    docs = list(dict.fromkeys(c.split("#")[0] for c in chunk_ids))
    fee = [FEE_LABELS[d] for d in docs if d in FEE_LABELS]
    scheme_docs = [d for d in docs if d in srcs and srcs[d].source_type == "M1_FACTSHEET"]
    other = [
        srcs[d].short_title
        for d in docs
        if d not in FEE_LABELS and d in srcs and d not in scheme_docs
    ]
    if len(scheme_docs) > 2:
        other.insert(0, f"Edelweiss scheme pages ({len(scheme_docs)})")
    else:
        other = [srcs[d].short_title for d in scheme_docs] + other
    parts = list(dict.fromkeys(other))
    if fee:
        parts.append("Fee Explainer – " + ", ".join(fee))
    dates = [date.fromisoformat(srcs[d].fetched_on) for d in docs if d in srcs]
    tail = f" Last updated {max(dates).isoformat()}." if dates else ""
    text = "Sources: " + "; ".join(parts) + "." + tail
    while word_count(text) > MAX_WORDS and len(parts) > 1:
        parts.pop(0 if len(parts) > 2 else -1)
        text = "Sources: " + "; ".join(parts) + "; and others." + tail
    return text


def finalize(bullets: list[Bullet], mode: str) -> Composed:
    body = [
        Bullet(trim_words(x.text, MAX_WORDS), list(dict.fromkeys(x.cites))) for x in bullets[:5]
    ]
    cited = [c for x in body for c in x.cites]
    body.append(Bullet(sources_bullet(cited), list(dict.fromkeys(cited))))
    return Composed([x.text for x in body], [x.cites for x in body], mode)


def template(frame: Frame) -> Composed:
    return finalize(frame.bullets, "template")


# --- Extractive fallback ------------------------------------------------------------------
_SENT = re.compile(r"(?<!\bNo\.)(?<!\bRs\.)(?<!\bvs\.)(?<=[.!?])\s+(?=[A-Z₹(])")
_ENDS = re.compile(r"[.!”\"')]\s*$")
_NOISE = re.compile(r"^(?:#|\||doc_id:|Source:|Example:)|https?://|www\.|·|\[\d+\]")
_BOILER = re.compile(
    r"subject to market risk|read all scheme related|deal only with registered|"
    r"investors should|not an offer|disclaimer|click here|download|log ?in|sign ?up|"
    r"read (?:this|more|the full)|want to (?:understand|know)|to recap|…|\?\s*$",
    re.I,
)
_BLOCK_START = re.compile(r"^\s*(?:[-*+]\s|\d+[.)]\s|#|\|)")


def _paragraphs(text: str) -> list[str]:
    """Re-join hard-wrapped markdown lines; list items, headings and table rows stay separate."""
    out: list[str] = []
    buf: list[str] = []
    for line in text.splitlines():
        if not line.strip() or _BLOCK_START.match(line):
            if buf:
                out.append(" ".join(buf))
            buf = [line.strip()] if line.strip() else []
            continue
        buf.append(line.strip())
    if buf:
        out.append(" ".join(buf))
    return out


def _sentences(chunk: Retrieved) -> list[str]:
    body = re.sub(r"\*{1,2}([^*]+)\*{1,2}", r"\1", chunk.text)
    if "#c" in chunk.chunk_id:  # drop the "<publisher>: <title>" context header line
        body = body.split("\n", 1)[1] if "\n" in body else ""
    out = []
    for para in _paragraphs(body):
        para = para.strip(" -*+")
        if not para or _NOISE.search(para):
            continue
        out += [
            s.strip()
            for s in _SENT.split(para)
            if word_count(s) >= 6 and _ENDS.search(s) and not _BOILER.search(s)
        ]
    return out


def extractive(
    query: str, chunks: list[Retrieved], *, rerank: bool = True, min_score: float = 0.0
) -> Composed | None:
    """Best-matching source sentences as bullets 1–5 (each cited); None if too little text.

    Only chunks scoring at least `min_score` and half the top score are used, so a weak
    neighbour cannot pad the answer with off-topic sentences.
    """
    top = max((c.score for c in chunks), default=0.0)
    if rerank and top < min_score:
        return None
    usable = [c for c in chunks if not rerank or c.score >= max(min_score, top / 2)]
    pool: list[tuple[str, str]] = []
    for ch in usable[:4]:
        pool += [(s, ch.chunk_id) for s in _sentences(ch)]
    seen: set[str] = set()
    pool = [(s, c) for s, c in pool if not (s.lower() in seen or seen.add(s.lower()))]
    if len(pool) < 5:
        return None
    if rerank:
        from pillar_a_kb import models

        scores = models.rerank(query, [s for s, _ in pool])
        ranked = [p for _, p in sorted(zip(scores, pool, strict=True), key=lambda t: -t[0])]
    else:
        ranked = pool
    picked = ranked[:5]
    bullets = [Bullet(trim_words(s, MAX_WORDS), [c]) for s, c in picked]
    return finalize(bullets, "extractive")


# --- LLM composer (optional) --------------------------------------------------------------
class LLMAnswer(BaseModel):
    bullets: list[str] = Field(min_length=N_BULLETS, max_length=N_BULLETS)
    bullet_citations: list[list[str]] = Field(min_length=N_BULLETS, max_length=N_BULLETS)


def llm_compose(
    query: str, frame: Frame | None, chunks: list[Retrieved], feedback: list[str] | None = None
) -> Composed:
    """Rephrase the frame (or answer from context) with the configured LLM. Raises LLMError."""
    from core.llm import complete
    from core.prompts import load_prompt

    ctx = "\n\n".join(f"[{c.chunk_id}] ({c.source_type}) {c.title}\n{c.text}" for c in chunks)
    draft = ""
    if frame:
        draft = "\n".join(
            f"{i + 1}. {b.text}  CITES={b.cites}" for i, b in enumerate(frame.bullets)
        )
        draft += f"\n6. {sources_bullet([c for b in frame.bullets for c in b.cites])}"
    user = (
        f"QUESTION:\n<<<\n{query}\n>>>\n\nCONTEXT CHUNKS:\n{ctx}\n\n"
        f"VERIFIED DRAFT (facts and calculations are correct; keep every number):\n"
        f"{draft or '(none — answer only from the context)'}"
    )
    if feedback:
        user += "\n\nYOUR PREVIOUS ANSWER FAILED THESE CHECKS; FIX THEM:\n- " + "\n- ".join(
            feedback
        )
    out = complete(
        load_prompt("rag_composer.v1.md"), user, schema=LLMAnswer, temperature=0.0, max_tokens=900
    )
    return Composed(
        [b.strip() for b in out.bullets], [list(c) for c in out.bullet_citations], "llm"
    )
