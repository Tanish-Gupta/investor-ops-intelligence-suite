"""Reviews CSV, synthetic fixtures, golden dataset and mock availability (Phase 2 tasks 2.5–2.9)."""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import date, datetime, timedelta

import pandas as pd
import pytest

from core.pii import REDACTED, contains_pii
from tests.data.conftest import DATA, ROOT, doc_text, load_yaml, normalise, sources

REVIEW_COLUMNS = ["review_id", "date", "rating", "title", "text", "platform", "user_name"]
FIXTURES = ROOT / "evals" / "fixtures"


def _read(path) -> pd.DataFrame:
    return pd.read_csv(path, keep_default_na=False, dtype={"review_id": str})


def _check_review_frame(df: pd.DataFrame) -> None:
    assert list(df.columns) == REVIEW_COLUMNS
    assert df["review_id"].is_unique
    assert (df["user_name"] == REDACTED).all()
    assert df["rating"].between(1, 5).all()
    assert (df["text"].str.len() > 0).all()
    assert df["platform"].isin(["android", "ios"]).all()
    pd.to_datetime(df["date"], format="%Y-%m-%d")  # ISO dates only


def keyword_theme(text: str, themes: list[dict]) -> str:
    """Deterministic keyword fallback (themeClassification.md §5); ties go to taxonomy order."""
    lowered = text.lower()
    best, best_hits = "Other", 0
    for t in themes:
        hits = sum(bool(re.search(rf"\b{re.escape(k)}\b", lowered)) for k in t["keywords"])
        if hits > best_hits:
            best, best_hits = t["label"], hits
    return best


# --- reviews.csv ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def reviews() -> pd.DataFrame:
    return _read(DATA / "reviews" / "reviews.csv")


def test_reviews_schema(reviews):
    _check_review_frame(reviews)
    assert len(reviews) > 1000


def test_reviews_have_no_pii(reviews):
    for col in ("title", "text"):
        leaks = [t for t in reviews[col] if t and contains_pii(t)]
        assert not leaks, f"{len(leaks)} {col} values still contain PII, e.g. {leaks[0][:80]!r}"


# --- fixtures ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "top_theme"),
    [
        ("reviews_fixture_nominee.csv", "Nominee Updates"),
        ("reviews_fixture_login.csv", "Login Issues"),
    ],
)
def test_fixture_top_theme(name, top_theme):
    df = _read(FIXTURES / name)
    _check_review_frame(df)
    assert not any(contains_pii(t) for t in df["text"])
    themes = load_yaml("themes.yaml")["themes"]
    counts = Counter(keyword_theme(t, themes) for t in df["text"])
    (winner, n), (_, runner_up) = counts.most_common(2)
    assert winner == top_theme
    assert n >= 2 * runner_up, "fixture top theme should win clearly"


def test_empty_fixture_has_header_only():
    df = _read(FIXTURES / "reviews_fixture_empty.csv")
    assert list(df.columns) == REVIEW_COLUMNS
    assert df.empty


# --- golden dataset ------------------------------------------------------------------------

GOLDEN_KEYS = {
    "id",
    "question",
    "expected_intent",
    "expected_facts",
    "expected_fee_points",
    "required_source_types",
    "expected_doc_ids",
    "reference_answer",
}


@pytest.fixture(scope="module")
def golden() -> list[dict]:
    return json.loads((ROOT / "evals" / "golden_dataset.json").read_text(encoding="utf-8"))


def test_golden_shape(golden):
    assert [g["id"] for g in golden] == ["G1", "G2", "G3", "G4", "G5"]
    for g in golden:
        assert GOLDEN_KEYS <= set(g), g["id"]
        assert g["expected_intent"] == "COMBINED"
        assert g["expected_facts"] and g["expected_fee_points"]


def test_golden_docs_cover_required_source_types(golden):
    reg = sources()
    for g in golden:
        types = {reg[d]["source_type"] for d in g["expected_doc_ids"]}
        assert set(g["required_source_types"]) <= types, g["id"]


def test_golden_evidence_is_in_corpus(golden):
    """Phase 2 exit criterion: every expected fact can be found in the corpus."""
    for g in golden:
        for ev in g["evidence"]:
            assert normalise(ev["text"]) in normalise(doc_text(ev["doc_id"])), f"{g['id']}: {ev}"
        cited = {ev["doc_id"] for ev in g["evidence"]}
        facts = [d for d in g["expected_doc_ids"] if d.startswith("F-")]
        assert set(facts) <= cited, f"{g['id']}: every expected factsheet needs evidence"


def test_golden_reference_answers_follow_six_bullets(golden):
    for g in golden:
        bullets = g["reference_answer"]
        assert len(bullets) == 6, g["id"]
        for b in bullets:
            assert len(b.split()) <= 30, f"{g['id']}: bullet over 30 words: {b}"
        assert bullets[5].startswith("Sources:"), g["id"]


def test_golden_numbers_are_grounded(golden):
    """Every % / ₹ figure in a reference answer is in its source docs or is a calculator result."""
    calculated = {
        "₹0.50",
        "₹9,999.50",
        "₹6",
        "₹99,994",
        "₹140",
        "₹99",
        "₹100",
        "₹1,00,000",
        "₹10,000",
        "0.0005%",
    }
    for g in golden:
        corpus = " ".join(
            normalise(doc_text(d))
            for d in {*g["expected_doc_ids"], *(e["doc_id"] for e in g["evidence"])}
        )
        for b in g["reference_answer"]:
            for num in re.findall(r"₹\d+(?:,\d+)*(?:\.\d+)?|\d+(?:\.\d+)?%", b):
                assert num in calculated or num.lower() in corpus, f"{g['id']}: {num} not grounded"


# --- availability.json ---------------------------------------------------------------------


def test_availability_calendar():
    data = json.loads((DATA / "availability.json").read_text(encoding="utf-8"))
    assert data["timezone"] == "Asia/Kolkata"
    assert data["mock"] is True
    days = data["days"]
    assert len(days) == 10
    dates = [date.fromisoformat(d["date"]) for d in days]
    assert dates == sorted(dates)
    assert all(d.weekday() < 5 for d in dates)
    for day in days:
        assert day["slots"], day["date"]
        assert any(s["status"] == "free" for s in day["slots"]), day["date"]
        for s in day["slots"]:
            start, end = datetime.fromisoformat(s["start"]), datetime.fromisoformat(s["end"])
            assert start.utcoffset() == timedelta(hours=5, minutes=30)
            assert end - start == timedelta(minutes=data["slot_minutes"])
            assert 9 <= start.hour and (end.hour, end.minute) <= (18, 0)
            assert s["status"] in {"free", "busy"}
