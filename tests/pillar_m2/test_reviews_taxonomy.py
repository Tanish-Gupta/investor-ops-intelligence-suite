from __future__ import annotations

import io
from datetime import date

import pytest

from core.pii import REDACTED
from pillar_m2_pulse.classifier import classify_keywords
from pillar_m2_pulse.reviews import ReviewInputError, load_reviews
from pillar_m2_pulse.taxonomy import load_taxonomy

from .conftest import EMPTY, NOMINEE, write_csv

# --- taxonomy ---------------------------------------------------------------------------------


def test_taxonomy_has_ten_labels_and_other_fallback():
    tax = load_taxonomy()
    assert len(tax.labels) == 10
    assert tax.fallback_label == "Other" and "Other" in tax.labels
    assert all(t.action_idea for t in tax.themes)


def test_keyword_patterns_match_inflections_and_word_boundaries():
    tax = load_taxonomy()
    wd = tax.get("Withdrawals & Timelines").pattern
    assert wd.search("My withdrawals are delayed")
    assert wd.search("withdrawing takes long")
    login = tax.get("Login Issues").pattern
    assert not login.search("spinach")  # 'pin' must not match inside a word


# --- loading / cleaning -----------------------------------------------------------------------


def test_aliases_are_normalised_and_ids_generated():
    csv = "content,score,at\n" + "\n".join(
        f"My SIP mandate failed again this month number {i},2,2026-09-2{i}" for i in range(1, 6)
    )
    pr = load_reviews(io.StringIO(csv))
    assert list(pr.df.columns[:3]) == ["review_id", "date", "rating"]
    assert pr.df["review_id"].tolist() == ["R00001", "R00002", "R00003", "R00004", "R00005"]
    assert (pr.df["user_name"] == REDACTED).all()


def test_missing_required_column_is_a_clear_error():
    with pytest.raises(ReviewInputError, match="rating"):
        load_reviews(io.StringIO("date,text\n2026-09-01,hello there my friend ok\n"))


def test_header_only_csv_gives_empty_result():
    assert load_reviews(EMPTY).empty


def test_pii_is_scrubbed_and_short_or_duplicate_reviews_dropped(tmp_path):
    path = write_csv(
        tmp_path / "r.csv",
        [
            ("2026-09-20", 1, "Nominee update failed, mail me at riya.k@example.com please"),
            ("2026-09-20", 1, "Nominee update failed, mail me at riya.k@example.com please"),
            ("2026-09-21", 2, "Too short"),
            ("2026-09-21", 1, "Call me on 9876543210 about my stuck withdrawal request"),
        ],
    )
    df = load_reviews(path).df
    assert len(df) == 2  # duplicate + < 5 words removed
    joined = " ".join(df["text"])
    assert "example.com" not in joined and "9876543210" not in joined
    assert REDACTED in joined


def test_window_and_end_date(tmp_path):
    rows = [("2026-01-01", 1, "old login otp problem never fixed by them")]
    rows += [("2026-09-20", 1, "login otp problem still not fixed today")]
    path = write_csv(tmp_path / "w.csv", rows)
    assert len(load_reviews(path).df) == 1  # 12-week window drops January
    early = load_reviews(path, end=date(2026, 2, 1)).df
    assert early["date"].dt.month.tolist() == [1]


def test_fixture_loads_cleanly():
    pr = load_reviews(NOMINEE)
    assert pr.stats["input"] == 15 and len(pr.df) == 15


# --- keyword classifier -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "theme"),
    [
        ("Unable to add nominee, verification pending for weeks", "Nominee Updates"),
        ("OTP never arrives so I cannot login", "Login Issues"),
        ("SIP mandate failed and autopay was not set", "SIP & Mandates"),
        ("Redemption money not credited after 5 days", "Withdrawals & Timelines"),
        ("Why was exit load charged on my redemption?", "Fees & Charges"),
        ("Need capital gains statement for ITR", "Statements & Tax Docs"),
        ("App keeps crashing and is very slow", "App Performance & UX"),
        ("Customer care never replies to my ticket", "Customer Support"),
        ("Great app, love it", "Other"),
    ],
)
def test_keyword_classifier(text, theme):
    assert classify_keywords(text, 2).theme == theme


def test_keyword_sentiment_from_rating():
    assert classify_keywords("crash", 1).sentiment == -1.0
    assert classify_keywords("crash", 5).sentiment == 1.0
