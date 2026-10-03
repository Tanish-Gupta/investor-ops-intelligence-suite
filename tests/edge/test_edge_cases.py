"""Phase 9.1: edge cases from docs/edgeCase.md that had no dedicated test."""

from __future__ import annotations

import time

import pytest

from config.settings import get_settings
from core import llm, state
from tests.pillar_b.conftest import run
from tests.pillar_m2.conftest import LOGIN, NOMINEE


def _has_index() -> bool:
    return (get_settings().data_dir / "lancedb").exists()


needs_index = pytest.mark.skipif(not _has_index(), reason="Unified KB index not built")


# --- Pillar A -----------------------------------------------------------------------------------
@needs_index
@pytest.mark.parametrize("query", ["", "   ", "asdf"])
def test_a15_empty_or_gibberish_asks_to_rephrase_without_llm(query, monkeypatch):
    from evals.sandbox import sandbox
    from pillar_a_kb.service import answer

    calls = []
    monkeypatch.setattr(llm, "complete", lambda *a, **k: calls.append(1))
    with sandbox():
        ans = answer(query)
    assert ans.status == "REFUSED" and not ans.bullets
    assert "Could you ask something" in ans.message
    assert not calls


@needs_index
def test_a17_llm_failure_falls_back_to_cited_template(monkeypatch, with_key):
    from evals.sandbox import sandbox
    from pillar_a_kb import composer
    from pillar_a_kb.service import answer

    def fail(*a, **k):
        raise llm.LLMError("timeout")

    monkeypatch.setattr(composer, "llm_compose", fail)
    with sandbox():
        ans = answer(
            "What is the exit load for the ELSS fund and why was I charged it?", use_llm=True
        )
    assert ans.status == "ANSWERED" and ans.mode == "template"
    assert len(ans.bullets) == 6 and ans.citations
    assert not ans.validation_errors


# --- M2 reviews ---------------------------------------------------------------------------------
def test_r01_missing_columns_named_and_aliases_accepted(tmp_path):
    from pillar_m2_pulse.reviews import ReviewInputError, load_reviews

    bad = tmp_path / "bad.csv"
    bad.write_text("date,stars\n2026-09-30,1\n")
    with pytest.raises(ReviewInputError, match="missing required column.*text"):
        load_reviews(bad)

    aliased = tmp_path / "aliased.csv"
    aliased.write_text(
        "at,score,content\n2026-09-30,1,the nominee update screen keeps failing for me\n"
    )
    assert len(load_reviews(aliased).df) == 1


# --- Pillar B -----------------------------------------------------------------------------------
def test_v04_new_pulse_mid_call_keeps_greeting_theme(make_session, workspace):
    from pillar_m2_pulse.pulse import run_pulse

    first = run_pulse(NOMINEE)
    s = make_session(pulse="latest")
    s.start()
    assert s.greeting_theme == "Nominee Updates"
    run_pulse(LOGIN)  # published while the call is in progress
    turns = run(s, "yes please", "Monday morning", "the second one", "yes")
    code = turns[-1].booking_code
    row = state.get_booking(code)
    assert row.greeting_theme == "Nominee Updates" and row.pulse_id == first.pulse_id
    nxt = make_session(pulse="latest")
    nxt.start()
    assert nxt.greeting_theme == "Login Issues"


def test_v13_hang_up_before_confirming_creates_nothing(make_session, workspace):
    s = make_session(pulse=None)
    run(s, "book a call about nominee updates", "Monday morning", "the first one")
    assert s.state != "BOOKED"
    assert s.end() is None
    assert s.hook_calls == []
    assert state.list_bookings() == [] and state.list_actions() == []
    assert not (workspace / "artifacts" / "bookings").exists() or not list(
        (workspace / "artifacts" / "bookings").iterdir()
    )


def test_v16_booking_code_collision_regenerates():
    from pillar_b_voice import booking

    taken: set[str] = set()

    def exists(code: str) -> bool:
        if len(taken) < 2:
            taken.add(code)
            return True
        return code in taken

    code = booking.generate(exists)
    assert booking.CODE_RE.match(code) and code not in taken
    with pytest.raises(booking.CodeSpaceExhausted):
        booking.generate(lambda _c: True)


# --- Cross-cutting ------------------------------------------------------------------------------
def test_x04_host_timezone_does_not_change_ist_logic(monkeypatch, workspace):
    from pillar_b_voice.greeting import build_greeting  # noqa: F401 - import under the new TZ

    monkeypatch.setenv("TZ", "America/New_York")
    time.tzset()
    try:
        now = state.now()
        assert now.utcoffset().total_seconds() == 5.5 * 3600
        assert str(now.tzinfo) == "Asia/Kolkata"
    finally:
        monkeypatch.undo()
        time.tzset()
