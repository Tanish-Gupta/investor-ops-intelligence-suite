"""Coverage questions ("which funds / sources do you have?"): answered from the corpus registry.

The registry (`data/sources.csv` + `config/scheme_aliases.yaml`) is the ground truth of what
Unified Search can answer, so these replies need no retrieval and cannot drift from the index.
The reply keeps the 6-bullet structure: five content bullets plus the sources bullet.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from pillar_a_kb.corpus import load_sources, schemes
from pillar_a_kb.router import rule_route

_ASK = r"(?:which|what|list|show|tell|name|share|give)"
_THING = (
    r"(?:mutual\s+)?(?:funds?|schemes?|sources?|documents?|docs|topics?|data|factsheets?|amcs?)"
)
_COVER = (
    r"(?:you|u)\s+(?:have|cover|know|support|use|track|answer|handle|offer)|"
    r"(?:available|covered|supported|included|indexed)|in\s+(?:your|the)\s+(?:sources|library|"
    r"knowledge|kb|corpus)"
)
_CATALOG = re.compile(
    rf"\b{_ASK}\b.*\b{_THING}\b.*(?:{_COVER})|"
    rf"\b{_ASK}\b.*(?:{_COVER}).*\b{_THING}\b|"
    r"\bwhat\s+(?:can|do)\s+(?:you|u)\s+(?:do|answer|help|cover|know)\b|"
    r"\bwhat\s+(?:questions|things)\s+can\s+i\s+ask\b|"
    r"^\s*(?:help|what can i ask\??)\s*$",
    re.I,
)


@dataclass(frozen=True)
class CatalogReply:
    bullets: list[str]
    bullet_docs: list[list[str]]  # doc_ids cited by each bullet


def is_catalog_question(text: str) -> bool:
    """True for questions about coverage itself, not about a scheme's or fee's facts."""
    if not _CATALOG.search(text or ""):
        return False
    plan = rule_route(text)
    return plan.scheme is None and not plan.fields and not plan.fee_types


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def catalog_reply() -> CatalogReply:
    srcs = load_sources()
    factsheets = [s for s in srcs if s.source_type == "M1_FACTSHEET"]
    fees = [s for s in srcs if s.source_type == "M2_FEE_EXPLAINER"]
    regulator = [s for s in srcs if s.source_type == "M1_REGULATOR"]
    funds = list(schemes())
    by_amc = {
        amc: sum(s.canonical.startswith(amc) for s in funds) for amc in ("Edelweiss", "Bajaj")
    }
    fee_topics = [s.title.replace("Fee Explainer: ", "") for s in fees]
    publishers = sorted({s.short_title.split(" – ")[0] for s in regulator})
    as_of = max(s.fetched_on for s in srcs if s.fetched_on)

    bullets = [
        f"I answer from {len(srcs)} documents covering {len(funds)} mutual funds: "
        f"{by_amc['Edelweiss']} Edelweiss schemes and {by_amc['Bajaj']} Bajaj Finserv schemes "
        f"(equity, index, hybrid, debt and ETF); see the fund library for the full list.",
        "For each fund I can give the exit load (and how long it applies), expense ratio, "
        "lock-in, minimum SIP and lump sum, benchmark and riskometer, taken from its factsheet "
        f"or scheme page ({len(factsheets)} pages).",
        f"The fee explainer covers why a charge applies and how it is worked out: "
        f"{_join(fee_topics)}.",
        f"Rules and definitions come from regulator and investor-education pages by "
        f"{_join(publishers)} ({len(regulator)} pages).",
        "Try: “What is the exit load for the ELSS fund and why was I charged it?” or “I "
        "redeemed my Flexi Cap fund after 8 months, what did it cost me?”",
        f"Sources: AMC scheme pages and factsheets ({len(factsheets)}); Fee Explainer ({len(fees)} "
        f"sections); SEBI and AMFI education pages. Last updated {as_of}.",
    ]
    fs_ids = [s.doc_id for s in factsheets]
    docs = [
        fs_ids,
        fs_ids,
        [s.doc_id for s in fees],
        [s.doc_id for s in regulator],
        [],
        [*fs_ids, *(s.doc_id for s in fees), *(s.doc_id for s in regulator)],
    ]
    return CatalogReply(bullets, docs)
