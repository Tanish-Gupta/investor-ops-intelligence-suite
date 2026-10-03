from decimal import Decimal

from pillar_a_kb import calculators as calc
from pillar_a_kb.textutil import first_sentences, numbers, trim_words, word_count


def test_inr_indian_grouping():
    assert calc.inr(Decimal("100000")) == "₹1,00,000"
    assert calc.inr(Decimal("6.5")) == "₹6.50"


def test_stamp_duty_on_10000_is_50_paise():
    c = calc.stamp_duty(Decimal("10000"))
    assert "₹0.50" in c.text
    assert Decimal("0.5") in c.numbers


def test_exit_load_statuses():
    assert calc.exit_load("ELSS").status == "no_load"
    assert calc.exit_load("FLEXI", 30).status == "inside"
    assert calc.exit_load("FLEXI", 243).status == "outside"
    assert calc.exit_load("FLEXI").window_days == 90
    liq = calc.exit_load("LIQ", 3)
    assert liq.status == "graded" and liq.rate_pct == "0.0060"
    assert calc.exit_load("LIQ", 9).status == "graded_nil"


def test_exit_load_user_amount():
    el = calc.exit_load("LC", 30, Decimal("50000"))
    assert "₹500" in el.calc.text and "₹49,500" in el.calc.text


def test_stt_applies_only_to_equity():
    assert calc.stt_applies("ELSS") and calc.stt_applies("Index")
    assert not calc.stt_applies("Liquid")


def test_textutil_numbers_normalise():
    assert numbers("₹1,00,000 at 0.0060% on day 3") == {
        Decimal("100000"),
        Decimal("0.006"),
        Decimal("3"),
    }


def test_textutil_trim_and_first_sentences():
    text = " ".join(["word"] * 40)
    assert word_count(trim_words(text, 30)) <= 30
    assert first_sentences("One two three. Four five six seven.", 4) == "One two three."


def test_exit_load_window_text_and_free_units():
    el = calc.exit_load("BSC", 120, Decimal(50000))
    assert (el.status, el.rate_pct, el.window_days) == ("inside", "1", 183)
    assert (el.window_label, el.free_units_pct) == ("6 months", 10)
    assert "₹50,000 of units beyond the free 10% within 6 months" in el.calc.text
    assert calc.exit_load("BSC", 200, None).status == "outside"
    assert calc.exit_load("BARB", 10, None).window_label == "15 days"
