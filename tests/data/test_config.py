"""Config contracts: themes.yaml, scheme_aliases.yaml and fee_rules.yaml."""

from __future__ import annotations

import re
from decimal import Decimal

from tests.data.conftest import doc_text, load_yaml, normalise, sources

TAXONOMY = [
    "Login Issues",
    "Nominee Updates",
    "KYC & Onboarding",
    "SIP & Mandates",
    "Withdrawals & Timelines",
    "Fees & Charges",
    "Statements & Tax Docs",
    "App Performance & UX",
    "Customer Support",
    "Other",
]


# --- themes.yaml ---------------------------------------------------------------------------


def test_theme_taxonomy_is_fixed():
    cfg = load_yaml("themes.yaml")
    assert [t["label"] for t in cfg["themes"]] == TAXONOMY
    assert cfg["max_active_themes"] == 5
    assert cfg["fallback_label"] == "Other"


def test_theme_voice_mapping():
    cfg = load_yaml("themes.yaml")
    topics = set(cfg["booking_topics"])
    assert len(topics) == 6
    by_label = {t["label"]: t for t in cfg["themes"]}
    for t in cfg["themes"]:
        assert t["description"].strip()
        assert t["greeting_phrase"].strip()
        assert t["voice_topic"] is None or t["voice_topic"] in topics, t["label"]
        if t["bookable_from_greeting"]:
            assert t["voice_topic"], f"{t['label']} is bookable but has no topic"
        if t["label"] != "Other":
            assert t["keywords"], f"{t['label']} needs fallback keywords"
    # docs/architecture/themeClassification.md §4
    assert by_label["Login Issues"]["bookable_from_greeting"] is False
    assert by_label["Login Issues"]["voice_topic"] == "Account & App Access"
    assert by_label["Nominee Updates"]["bookable_from_greeting"] is True
    assert by_label["Nominee Updates"]["voice_topic"] == "Nominee Updates"
    assert by_label["Fees & Charges"]["voice_topic"] == "Statements/Tax Docs"


def test_theme_keywords_are_lowercase_and_unique_per_theme():
    for t in load_yaml("themes.yaml")["themes"]:
        kws = t["keywords"]
        assert all(k == k.lower() for k in kws), t["label"]
        assert len(kws) == len(set(kws)), t["label"]


# --- scheme_aliases.yaml -------------------------------------------------------------------


def test_scheme_aliases_are_unambiguous():
    cfg = load_yaml("scheme_aliases.yaml")
    seen: dict[str, str] = {}
    for s in cfg["schemes"]:
        for alias in s["aliases"]:
            assert alias == alias.lower()
            assert alias not in seen, f"'{alias}' maps to both {seen[alias]} and {s['id']}"
            seen[alias] = s["id"]
    ids = {s["id"] for s in cfg["schemes"]}
    assert {"ELSS", "FLEXI", "LC", "IDX", "LIQ"} <= ids  # M1 Edelweiss schemes
    assert len(ids) == len(cfg["schemes"]) == 30  # + 25 Bajaj Finserv schemes


def test_scheme_alias_doc_ids_exist_and_match():
    reg = sources()
    for s in load_yaml("scheme_aliases.yaml")["schemes"]:
        for doc_id in s["doc_ids"]:
            assert reg[doc_id]["scheme"] == s["canonical"]
            assert reg[doc_id]["category"] == s["category"]


# --- fee_rules.yaml ------------------------------------------------------------------------


def _walk(node, path=""):
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _walk(v, f"{path}.{k}" if path else k)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _walk(v, f"{path}[{i}]")
    else:
        yield path, node


def test_fee_rules_reference_known_docs_and_urls():
    reg = sources()
    urls = {r["url"] for r in reg.values()}
    for path, value in _walk(load_yaml("fee_rules.yaml")):
        key = path.rsplit(".", 1)[-1]
        if key.endswith("doc_id"):
            assert value in reg, f"{path}: unknown doc_id {value}"
        if key == "source":
            assert value in urls, f"{path}: source URL is not in sources.csv"
        if key.endswith("rate_pct"):
            assert isinstance(value, str), f"{path}: keep rates as strings for Decimal"
            assert Decimal(value) >= 0


def test_fee_rule_values_match_their_sources():
    rules = load_yaml("fee_rules.yaml")
    assert "0.005%" in doc_text(rules["stamp_duty"]["doc_id"])
    assert "0.001%" in doc_text(rules["stt"]["doc_id"])
    liq = rules["exit_load"]["schemes"]["LIQ"]
    factsheet = normalise(doc_text(liq["doc_id"]))
    for slab in liq["slabs"]:
        assert f"day {slab['day']} · {slab['rate_pct']}%" in factsheet
    assert "day 7 onwards · nil" in factsheet
    flexi = rules["exit_load"]["schemes"]["FLEXI"]["slabs"][0]
    assert f"{flexi['min_days']}-{flexi['max_days']} days" in normalise(doc_text("F-FLEXI-01"))


def test_liquid_slabs_decrease_and_end_at_day_7():
    liq = load_yaml("fee_rules.yaml")["exit_load"]["schemes"]["LIQ"]
    days = [s["day"] for s in liq["slabs"]]
    rates = [Decimal(s["rate_pct"]) for s in liq["slabs"]]
    assert days == list(range(1, 7))
    assert rates == sorted(rates, reverse=True)
    assert liq["nil_from_day"] == 7


def test_stamp_duty_worked_example():
    rate = Decimal(load_yaml("fee_rules.yaml")["stamp_duty"]["rate_pct"]) / 100
    assert Decimal(10_000) * rate == Decimal("0.50")
    assert Decimal(100_000) * rate == Decimal("5")


def test_scheme_ids_line_up_across_configs():
    alias_ids = {s["id"] for s in load_yaml("scheme_aliases.yaml")["schemes"]}
    fee_ids = set(load_yaml("fee_rules.yaml")["exit_load"]["schemes"])
    assert alias_ids == fee_ids
    cats = {s["category"] for s in load_yaml("scheme_aliases.yaml")["schemes"]}
    stt = load_yaml("fee_rules.yaml")["stt"]
    assert set(stt["applies_to_categories"]) | set(stt["exempt_categories"]) == cats
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(load_yaml("fee_rules.yaml")["as_of"]))
