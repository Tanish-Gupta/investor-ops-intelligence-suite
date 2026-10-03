from __future__ import annotations

import pandas as pd
import pytest
from pydantic import ValidationError

from core import llm
from pillar_m2_pulse import classifier
from pillar_m2_pulse.classifier import ThemeCache, _batch_schema, classify_frame
from pillar_m2_pulse.ranking import active_themes, rank_themes
from pillar_m2_pulse.taxonomy import load_taxonomy


def _frame(texts: list[str], ratings: list[int] | None = None, day: str = "2026-09-25"):
    n = len(texts)
    return pd.DataFrame(
        {
            "review_id": [f"r{i}" for i in range(n)],
            "date": pd.to_datetime([day] * n),
            "rating": ratings or [1] * n,
            "title": [""] * n,
            "text": texts,
        }
    )


# --- LLM classifier path (mocked) -------------------------------------------------------------


def test_schema_rejects_off_taxonomy_labels():
    schema = _batch_schema(load_taxonomy().labels)
    ok = schema.model_validate({"items": [{"id": "0", "theme": "Login Issues"}]})
    assert ok.items[0].theme == "Login Issues"
    with pytest.raises(ValidationError):
        schema.model_validate({"items": [{"id": "0", "theme": "Trading Bugs"}]})


def test_llm_disabled_by_default_uses_keywords(monkeypatch):
    called = []
    monkeypatch.setattr(llm, "complete", lambda *a, **k: called.append(1))
    out, stats = classify_frame(_frame(["OTP not received for login"]))
    assert called == [] and stats["keyword"] == 1
    assert out["theme"].tolist() == ["Login Issues"]


def test_llm_path_used_when_enabled_and_key_present(with_key, monkeypatch, tmp_path):
    schema = _batch_schema(load_taxonomy().labels)
    calls = []

    def fake(system, msg, schema=None, **_):
        calls.append(msg)
        assert "Allowed themes" in system and "Nominee Updates" in system
        return schema.model_validate(
            {
                "items": [
                    {"id": "0", "theme": "Nominee Updates", "sentiment": -0.7, "confidence": 0.9},
                    {"id": "1", "theme": "Login Issues", "sentiment": -0.2, "confidence": 0.3},
                ]
            }
        )

    monkeypatch.setattr(llm, "complete", fake)
    assert schema  # built once and cached
    cache = ThemeCache(tmp_path / "cache.json")
    df = _frame(["Nominee change stuck in review", "Customer care never replied to my ticket"])
    out, stats = classify_frame(df, use_llm=True, cache=cache)
    assert out["theme"].tolist() == ["Nominee Updates", "Customer Support"]  # 2nd: low conf → kw
    assert out["method"].tolist() == ["llm", "keyword"]
    assert stats["low_conf_fallback"] == 1 and len(calls) == 1

    # cached: second run makes no LLM call
    calls.clear()
    out2, stats2 = classify_frame(df, use_llm=True, cache=ThemeCache(tmp_path / "cache.json"))
    assert calls == [] and stats2["cached"] == 2
    assert out2["theme"].tolist() == out["theme"].tolist()


def test_llm_error_falls_back_to_keywords(with_key, monkeypatch):
    def boom(*_a, **_k):
        raise llm.LLMError("down")

    monkeypatch.setattr(llm, "complete", boom)
    out, stats = classify_frame(_frame(["SIP mandate failed again this month"]), use_llm=True)
    assert out["theme"].tolist() == ["SIP & Mandates"]
    assert stats["llm_errors"] == 1 and stats["keyword"] == 1


def test_llm_requested_without_key_never_calls(monkeypatch):
    monkeypatch.setattr(llm, "complete", lambda *a, **k: pytest.fail("no key → no call"))
    out, _ = classify_frame(_frame(["Nominee update pending"]), use_llm=True)
    assert out["theme"].tolist() == ["Nominee Updates"]


def test_batches_respect_batch_size(with_key, monkeypatch):
    monkeypatch.setenv("PULSE_LLM_BATCH", "2")
    from config.settings import get_settings

    get_settings.cache_clear()
    sizes = []

    def fake(system, msg, schema=None, **_):
        import json

        items = json.loads(msg.split("\n", 1)[1])
        sizes.append(len(items))
        return schema.model_validate(
            {"items": [{"id": it["id"], "theme": "Other", "confidence": 0.9} for it in items]}
        )

    monkeypatch.setattr(classifier.llm, "complete", fake)
    classify_frame(_frame([f"generic review text number {i}" for i in range(5)]), use_llm=True)
    assert sizes == [2, 2, 1]


# --- ranking ----------------------------------------------------------------------------------


def test_other_is_never_top_and_min_evidence_applies():
    texts = ["Great app love it"] * 30 + ["OTP login failing again"] * 4
    stats, top = rank_themes(classify_frame(_frame(texts))[0])
    assert stats and top is None  # Login has only 4 reviews (< 5); Other is never eligible


def test_top_theme_and_deterministic_tie_break():
    texts = ["OTP login failing again"] * 6 + ["Nominee update pending"] * 6
    df = classify_frame(_frame(texts))[0]
    stats, top = rank_themes(df)
    assert top == "Login Issues"  # equal score & count → alphabetical
    assert [s.theme for s in active_themes(stats)] == ["Login Issues", "Nominee Updates"]


def test_negativity_and_share_drive_score():
    texts = ["OTP login failing again"] * 10 + ["Nominee update pending"] * 6
    ratings = [5] * 10 + [1] * 6
    stats, top = rank_themes(classify_frame(_frame(texts, ratings))[0])
    by = {s.theme: s for s in stats}
    assert by["Login Issues"].negativity == 0.0 and by["Nominee Updates"].negativity == 0.8
    assert top == "Nominee Updates"  # 0.6*0.375 + 0.25*0.8 > 0.6*0.625 + 0 (growth equal)


def test_empty_frame():
    assert rank_themes(_frame([]).iloc[0:0]) == ([], None)
