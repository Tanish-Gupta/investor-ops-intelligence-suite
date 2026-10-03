"""Template frames: structure only (no index or models needed)."""

import pytest

from pillar_a_kb import composer as comp
from pillar_a_kb.router import rule_route
from pillar_a_kb.service import split_advice
from pillar_a_kb.textutil import word_count

QUESTIONS = [
    "What is the exit load for the ELSS fund and why was I charged it?",
    "I redeemed my Flexi Cap units 8 months after buying. What exit load applies?",
    "I withdrew from the liquid fund 3 days after investing — why is the amount lower?",
    "What is the expense ratio of the Index fund?",
    "My ₹10,000 SIP in the Large Cap fund showed ₹9,999.50 invested. Why the difference?",
    "What is the exit load?",
    "What is STT?",
    "What is the lock-in of the ELSS fund?",
    "Benchmark of the Large Cap fund",
    "Compare the expense ratio of Large Cap and Nifty 50 Index fund",
]


@pytest.mark.parametrize("q", QUESTIONS)
def test_template_has_six_cited_short_bullets(q):
    frame = comp.build_frame(rule_route(q))
    assert frame is not None
    out = comp.template(frame)
    assert len(out.bullets) == 6
    assert all(word_count(b) <= comp.MAX_WORDS for b in out.bullets)
    assert all(cites for cites in out.bullet_cites)
    assert out.bullets[-1].startswith("Sources:")
    cited = {c for ids in out.bullet_cites for c in ids}
    assert cited <= set(frame.pinned)


def test_elss_false_premise_is_corrected():
    frame = comp.build_frame(rule_route(QUESTIONS[0]))
    assert frame.premise and "0%" in frame.premise
    text = " ".join(b.text for b in frame.bullets)
    assert "no exit load" in text and "stamp duty" in text.lower()


def test_compare_frame_lists_each_scheme():
    frame = comp.build_frame(rule_route(QUESTIONS[-1]))
    assert frame.topic == "compare_expense_ratio"
    assert "0.67%" in frame.bullets[0].text and "0.14%" in frame.bullets[0].text


def test_open_question_has_no_template():
    assert comp.build_frame(rule_route("Who decides the cap on the expense ratio?")) is None


def test_split_advice_keeps_the_factual_clause():
    rest = split_advice(
        "What's the exit load of the Flexi Cap fund, and should I switch to the index fund?"
    )
    assert rest and "exit load" in rest and "switch" not in rest
    assert split_advice("What is the exit load of the ELSS fund?") is None
