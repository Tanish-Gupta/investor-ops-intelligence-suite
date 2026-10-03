from decimal import Decimal

import pytest

from pillar_a_kb.router import parse_scenario, resolve_schemes, rule_route


@pytest.mark.parametrize(
    ("text", "scheme"),
    [
        ("exit load of the ELSS fund", "ELSS"),
        ("Edelweiss Flexi Cap", "FLEXI"),
        ("the liquid fund", "LIQ"),
        ("nifty 50 index fund TER", "IDX"),
        ("Large Cap minimum SIP", "LC"),
        ("Bajaj Finserv Small Cap exit load", "BSC"),
        ("exit load of the small cap fund", "BSC"),
        ("bajaj flexi cap", "BFLEXI"),
        ("Expense ratio of the Bajaj Nifty 50 ETF", "BETF50"),
    ],
)
def test_resolve_schemes_aliases(text, scheme):
    assert [s.id for s in resolve_schemes(text)][:1] == [scheme]


def test_resolve_schemes_keeps_mention_order():
    assert [s.id for s in resolve_schemes("Large Cap vs ELSS vs liquid")] == ["LC", "ELSS", "LIQ"]


@pytest.mark.parametrize(
    ("text", "days"),
    [
        ("8 months after buying", 243),
        ("3 days after investing", 3),
        ("on day 2", 2),
        ("after a year", 365),
        ("two weeks", 14),
    ],
)
def test_parse_scenario_holding_days(text, days):
    assert parse_scenario(text).holding_days == days


def test_parse_scenario_amounts_and_transaction():
    sc = parse_scenario("My ₹10,000 SIP showed ₹9,999.50 invested")
    assert sc.amounts == (Decimal("10000"), Decimal("9999.50"))
    assert sc.transaction == "purchase"
    assert parse_scenario("I redeemed 2 lakh").amounts == (Decimal("200000"),)
    assert parse_scenario("I redeemed 2 lakh").transaction == "redemption"


def test_g1_is_combined_exit_load():
    plan = rule_route("What is the exit load for the ELSS fund and why was I charged it?")
    assert plan.intent == "COMBINED"
    assert plan.scheme.id == "ELSS"
    assert "exit_load" in plan.fee_types and "exit_load" in plan.fields


def test_g5_infers_stamp_duty():
    plan = rule_route(
        "My ₹10,000 SIP in the Large Cap fund showed ₹9,999.50 invested. "
        "What is the minimum SIP and why the difference?"
    )
    assert plan.scheme.id == "LC"
    assert plan.fee_types == ["stamp_duty"]
    assert "min_investment" in plan.fields


def test_charged_on_day_n_infers_exit_load():
    plan = rule_route("I was charged on day 2 for the liquid fund, why?")
    assert plan.fee_types == ["exit_load"]
    assert plan.scenario.holding_days == 2


def test_unsupported_scheme_and_unknown_fee():
    assert rule_route("Exit load of XYZ Small Cap?").other_scheme
    assert rule_route("Is there GST on the expense ratio?").unknown_fee == "GST"


def test_generic_article_is_not_scheme_specific():
    assert not rule_route("What is the exit load?").needs_scheme
    assert not rule_route("Who decides the cap on the expense ratio?").needs_scheme
    assert rule_route("What is the exit load of the equity fund?").needs_scheme


def test_open_ended_question_flag():
    assert rule_route("Who decides the cap on the expense ratio?").open_ended
    assert not rule_route("What is the expense ratio of the ELSS fund?").open_ended


@pytest.mark.parametrize(
    ("text", "other"),
    [
        ("Exit load of XYZ Small Cap?", "XYZ Small Cap"),
        ("Exit load of SBI small cap fund", "SBI small cap fund"),
        ("Nippon India Small Cap exit load", "Nippon India Small Cap"),
        ("Parag Parikh Flexi Cap expense ratio", "Parag Parikh Flexi Cap"),
    ],
)
def test_other_amc_brand_blocks_generic_alias(text, other):
    plan = rule_route(text)
    assert plan.scheme is None
    assert plan.other_scheme == other


def test_supported_brand_and_comparison_still_resolve():
    assert [s.id for s in resolve_schemes("Compare ELSS and Bajaj small cap")] == ["ELSS", "BSC"]
    assert [s.id for s in resolve_schemes("HDFC vs bajaj finserv large cap")] == ["BLC"]


def test_cost_me_is_a_charge_question():
    plan = rule_route("I redeemed my Bajaj Flexi Cap fund after 2 months, what did it cost me?")
    assert plan.scheme.id == "BFLEXI"
    assert plan.fee_types == ["exit_load"]
