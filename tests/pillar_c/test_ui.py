"""Approvals page (Streamlit AppTest): empty state, approve-all, reject, email preview with Market
Context, and the pre-booking notes register (booking code visible after approval)."""

from __future__ import annotations

from core import state
from tests.ui_helpers import goto, md, open_app

BOOK = ("book a nominee call", "monday morning", "1", "yes")


def test_empty_states(hitl):
    at = goto(open_app(), "approvals")
    assert not at.exception
    assert "No actions yet" in md(at)
    assert "Pre-booking notes register" in md(at) and "No entries yet" in md(at)


def test_approve_all_from_ui_updates_notes(call):
    code = call(*BOOK)
    at = goto(open_app(), "approvals")
    assert not at.exception
    assert code in md(at)
    assert md(at).count("Awaiting approval") == 3  # hold, notes line, email draft
    at.button(key="hitl_approve_all").click().run()
    assert not at.exception
    assert any("Approved all" in s.value for s in at.success)
    assert state.get_booking(code).status == "CONFIRMED"
    assert "All follow-ups done" in md(at)
    assert 'class="io-stamp approved"' in md(at)
    reg = next(m.value for m in at.markdown if 'class="io-register"' in m.value)
    assert f'<td class="code">{code}</td>' in reg


def test_email_preview_highlights_market_context(call):
    from pillar_c_mcp import actions
    from pillar_c_mcp.plan import GMAIL_DRAFT
    from pillar_m2_pulse.pulse import run_pulse
    from tests.pillar_m2.conftest import NOMINEE

    pulse = run_pulse(NOMINEE)
    code = call(*BOOK, pulse=pulse)
    at = goto(open_app(), "approvals")
    mail = next(
        m.value for m in at.markdown if 'class="io-mail"' in m.value and "<mark>" in m.value
    )
    assert code in mail and "[REDACTED]" in mail
    draft = next(v for v in actions.actions_for(code) if v.tool == GMAIL_DRAFT)
    assert draft.args["market_context"].strip()[:30] in mail


def test_reject_from_popover(call):
    from pillar_c_mcp import actions

    code = call(*BOOK)
    first = actions.actions_for(code)[0]
    at = goto(open_app(), "approvals")
    at.text_input(key=f"reason_{first.id}").input("duplicate request")
    at.button(key=f"reject_{first.id}").click().run()
    assert not at.exception
    assert any("Rejected" in s.value for s in at.success)
    assert next(v for v in actions.actions_for(code) if v.id == first.id).status == "REJECTED"
