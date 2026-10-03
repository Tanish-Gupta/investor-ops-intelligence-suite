from __future__ import annotations

import json

import pytest

from core import llm, notes, pii, state
from pillar_m2_pulse import pulse as pulse_mod
from pillar_m2_pulse.market_context import MATCH_LINE, build_market_context
from pillar_m2_pulse.pulse import PulseCopy, get_latest_pulse, run_pulse, word_count
from pillar_m2_pulse.reviews import ReviewInputError

from .conftest import EMPTY, FULL, LOGIN, NOMINEE, write_csv

# --- exit criteria (M-P) ----------------------------------------------------------------------


def test_nominee_fixture_top_theme(workspace):
    p = run_pulse(NOMINEE)
    assert p.top_theme == "Nominee Updates"
    assert p.pulse_id == "PULSE-2026-W40"


def test_login_fixture_top_theme(workspace):
    assert run_pulse(LOGIN).top_theme == "Login Issues"


def test_empty_fixture_is_rejected_and_nothing_saved(workspace):
    with pytest.raises(ReviewInputError):
        run_pulse(EMPTY)
    assert get_latest_pulse() is None


@pytest.mark.parametrize("src", [NOMINEE, LOGIN, FULL])
def test_pulse_rubric_words_ideas_structure_no_pii(workspace, src):
    p = run_pulse(src)
    assert p.word_count <= 250 and word_count(p.pulse_md) == p.word_count
    assert p.action_idea_count == 3 and len(p.action_ideas) == 3
    ideas_section = p.pulse_md.split("## Action Ideas", 1)[1]
    assert sum(1 for ln in ideas_section.splitlines() if ln[:2] in {"1.", "2.", "3."}) == 3
    for heading in ("# Weekly Product Pulse", "## Top Themes", "## What Users Are Saying"):
        assert heading in p.pulse_md
    assert not pii.contains_pii(p.pulse_md)
    for q in p.quotes:
        assert 1 <= len(q["text"].split()) <= 41


def test_full_dataset_has_three_themes_and_three_quotes(workspace):
    p = run_pulse(FULL)
    assert len(p.top3) == 3 and len(p.quotes) == 3
    assert p.top_theme == p.top3[0]["theme"] and p.top_theme != "Other"
    assert f"— {pii.REDACTED}, ★" in p.pulse_md


def test_quotes_never_leak_pii(workspace, tmp_path):
    rows = [
        (
            f"2026-09-2{i % 9 + 1}",
            1,
            f"Nominee update stuck for {i + 2} weeks, my number is 98765432{i:02d} and nobody "
            "calls back",
        )
        for i in range(8)
    ]
    p = run_pulse(write_csv(tmp_path / "pii.csv", rows))
    assert p.top_theme == "Nominee Updates"
    assert "98765432" not in p.pulse_md and not pii.contains_pii(p.pulse_md)


# --- persistence ------------------------------------------------------------------------------


def test_persists_db_artifacts_and_notes_once(workspace):
    p = run_pulse(NOMINEE)
    row = state.get_pulse(p.pulse_id)
    assert row and row.top_theme == "Nominee Updates"
    art = workspace / "artifacts"
    assert (art / f"pulse_{p.pulse_id}.md").read_text() == p.pulse_md
    data = json.loads((art / f"pulse_{p.pulse_id}.json").read_text())
    assert data["top_theme"] == "Nominee Updates" and data["action_idea_count"] == 3
    assert (art / f"classified_{p.pulse_id}.csv").exists()
    run_pulse(NOMINEE)  # re-run same week → notes entry not duplicated
    assert notes.read_notes().count(f"[{p.pulse_id}]") == 1

    latest = get_latest_pulse()
    assert latest.pulse_id == p.pulse_id and latest.top3[0]["theme"] == "Nominee Updates"


def test_persist_false_writes_nothing(workspace):
    run_pulse(NOMINEE, persist=False)
    assert get_latest_pulse() is None and not notes.read_notes()


# --- LLM copy (mocked) ------------------------------------------------------------------------


def _fake_copy(ideas, summaries=("Users cannot change nominees and see no status",)):
    def fake(system, msg, schema=None, **_):
        assert schema is PulseCopy and "EXACTLY 3" in system
        return PulseCopy(summaries=list(summaries), ideas=list(ideas))

    return fake


def test_llm_copy_used_when_enabled(workspace, with_key, monkeypatch):
    ideas = [
        "Add an in-app nominee status tracker",
        "Email users when nominee verification completes",
        "Explain nomination deadlines on the profile screen",
    ]
    monkeypatch.setattr(llm, "complete", _fake_copy(ideas))
    monkeypatch.setattr(pulse_mod, "classify_frame", _keyword_only())
    p = run_pulse(NOMINEE, use_llm=True)
    assert p.copy_method == "llm" and p.action_ideas == ideas
    assert "Users cannot change nominees" in p.pulse_md


def test_llm_copy_with_advice_is_rejected(workspace, with_key, monkeypatch):
    bad = ["You should invest in ELSS funds now", "Add a tracker", "Explain deadlines"]
    monkeypatch.setattr(llm, "complete", _fake_copy(bad))
    monkeypatch.setattr(pulse_mod, "classify_frame", _keyword_only())
    p = run_pulse(NOMINEE, use_llm=True)
    assert p.copy_method == "template" and "invest" not in " ".join(p.action_ideas).lower()


def test_llm_copy_failure_uses_templates(workspace, with_key, monkeypatch):
    def boom(*_a, **_k):
        raise llm.LLMError("timeout")

    monkeypatch.setattr(llm, "complete", boom)
    monkeypatch.setattr(pulse_mod, "classify_frame", _keyword_only())
    p = run_pulse(NOMINEE, use_llm=True)
    assert p.copy_method == "template" and len(p.action_ideas) == 3


def test_pulse_copy_schema_enforces_three_short_ideas():
    with pytest.raises(ValueError):
        PulseCopy(ideas=["a", "b"])
    with pytest.raises(ValueError):
        PulseCopy(ideas=["a", "b", " ".join(["word"] * 30)])


def _keyword_only():
    from pillar_m2_pulse.classifier import classify_frame

    return lambda df, **kw: classify_frame(df, use_llm=False)


# --- budget -----------------------------------------------------------------------------------


def test_budget_trims_summaries_then_quotes(workspace, monkeypatch):
    long = " ".join(["detail"] * 40)  # 3 × 40-word summaries push the pulse over 250 words
    monkeypatch.setattr(pulse_mod, "_template_summary", lambda t: long)
    p = run_pulse(FULL, persist=False)
    assert p.word_count <= 250
    assert long not in p.pulse_md  # summaries are the first thing dropped
    assert len(p.quotes) == 3 and p.pulse_md.count(f"— {pii.REDACTED}, ★") == 3


def test_word_count_ignores_markdown_markers():
    assert word_count("# Title here\n- one two\n1. three — four\n**bold** text") == 8


# --- market context ---------------------------------------------------------------------------


def test_market_context_template_and_topic_match(workspace):
    p = run_pulse(NOMINEE)
    mc = build_market_context(p, "Nominee Updates")
    assert '"Nominee Updates"' in mc and p.pulse_id in mc and mc.endswith(MATCH_LINE)
    assert len(mc.split()) <= 60
    assert MATCH_LINE not in build_market_context(p, "SIP/Mandates")
    assert MATCH_LINE not in build_market_context(p, None)
    assert p.market_context == build_market_context(p)
    assert not pii.contains_pii(mc)


def test_market_context_maps_login_to_account_access(workspace):
    p = run_pulse(LOGIN)
    assert build_market_context(p, "Account & App Access").endswith(MATCH_LINE)


def test_market_context_without_pulse():
    assert "no Weekly Pulse" in build_market_context(None, "Nominee Updates")
