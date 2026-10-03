"""Health summary, pulse autobuild, voice flow, opt-in speech (mocked), graceful degradation."""

from __future__ import annotations

import sys
import types

import pytest

from config.settings import get_settings
from core import state
from tests.ui_helpers import click_label, goto, md, open_app, say


@pytest.fixture
def app(workspace):
    from pillar_c_mcp.client import reset_bundles

    reset_bundles()
    yield open_app
    reset_bundles()


def test_health_checks_offline(app):
    from dashboard import health

    names = {c.name: c for c in health.checks()}
    assert names["MCP tool server"].ok is True and "5 tools" in names["MCP tool server"].detail
    assert names["LLM"].ok is None and "deterministic" in names["LLM"].detail
    assert names["Weekly Pulse"].ok is None
    assert health.summary()["pending_approvals"] == 0


def test_mcp_offline_is_reported(app, monkeypatch):
    from dashboard import health
    from pillar_c_mcp import client

    def boom(*a, **k):
        raise ConnectionError("server down")

    monkeypatch.setattr(client, "get_client", boom)
    chk = next(c for c in health.checks() if c.name == "MCP tool server")
    assert chk.ok is False and "offline" in chk.detail


def test_full_demo_flow_in_one_app(app):
    from pillar_m2_pulse.pulse import run_pulse
    from tests.pillar_m2.conftest import NOMINEE

    pulse = run_pulse(NOMINEE)
    at = goto(app(), "book")
    assert not at.exception
    assert pulse.top_theme in md(at)  # call brief
    assert any("Nominee Updates" in m.value for m in at.markdown)  # theme-aware greeting
    for u in ("yes please", "monday morning", "1", "yes", "no thanks"):
        at = say(at, u)
        assert not at.exception and not at.error
    code = state.list_bookings()[0].booking_code
    assert code in md(at)  # booking ticket
    assert "Sent for approval" in md(at)  # hand-off
    at.button(key="voice_to_approvals").click()
    at.run()
    assert at.button(key="hitl_approve_all")  # CTA switched to Approvals
    at = goto(at, "approvals")  # AppTest re-runs its pinned page, so pin Approvals
    assert code in md(at) and md(at).count("Awaiting approval") == 3
    at.button(key="hitl_approve_all").click()
    at.run()
    assert any("Approved all" in s.value for s in at.success)
    reg = next(m.value for m in at.markdown if 'class="io-register"' in m.value)
    row = next(r for r in reg.split("<tr>") if code in r)
    assert pulse.pulse_id in row  # booking code + the pulse that briefed the call


def test_quick_reply_chips_complete_a_booking(app):
    from pillar_m2_pulse.pulse import run_pulse
    from tests.pillar_m2.conftest import NOMINEE

    run_pulse(NOMINEE)
    at = goto(app(), "book")
    at = click_label(at, "Nominee Updates")
    at = click_label(at, "Earliest available")
    first_slot = next(b.label for b in at.button if b.key and b.key.startswith("voice_opt_"))
    at = click_label(at, first_slot)  # chip carries the slot label; UI sends "1"
    at = click_label(at, "Yes")
    assert not at.exception and not at.error
    booking = state.list_bookings()[0]
    assert booking.topic == "Nominee Updates"
    assert booking.booking_code in md(at)


def test_cross_page_ctas_navigate(app):
    at = app()
    at.button(key="home_customer").click()  # Home -> Customer portal (Ask)
    at = at.run()
    assert at.button(key="kb_build")  # empty library -> one clear action
    at = goto(at, "home")
    at.button(key="home_admin").click()  # Home -> Admin portal (Review pulse)
    at = at.run()
    assert at.button(key="pulse_run")
    at = goto(at, "approvals")
    at.button(key="hitl_empty_cta").click()
    at.run()
    assert "Book an advisor call" in md(at) and at.text_input(key="voice_text")


def test_voice_page_refuses_advice_and_new_call(app):
    at = goto(app(), "book")
    at = say(at, "Which fund will give me 20% returns?")
    assert any("Refused" in c.value for c in at.caption)
    at.button(key="voice_new").click()
    at.run()
    assert not at.exception
    assert not any("Refused" in c.value for c in at.caption)


def test_failing_page_degrades_gracefully(app, monkeypatch):
    import pillar_a_kb.ui as ask

    monkeypatch.setattr(ask, "render", lambda: (_ for _ in ()).throw(RuntimeError("x")))
    at = goto(app(), "ask")
    assert not at.exception
    assert any("temporarily unavailable" in e.value for e in at.error)
    at = goto(at, "book")  # other pages still render
    assert not at.error and at.text_input(key="voice_text")


def test_pulse_autobuilds_once_when_enabled(app, monkeypatch):
    from pillar_m2_pulse.pulse import get_latest_pulse

    monkeypatch.setenv("PULSE_AUTOBUILD", "true")
    get_settings.cache_clear()
    assert get_latest_pulse() is None
    at = goto(app(), "book")
    assert not at.exception
    p = get_latest_pulse()
    assert p is not None and p.top_theme in md(at)  # briefing shows the auto-built theme
    get_settings.cache_clear()


def test_autobuild_off_keeps_generic_greeting(app):
    at = goto(app(), "book")
    assert "standard greeting" in md(at)


# --- speech (opt-in, mocked) ---------------------------------------------------------------------
def test_speech_off_by_default(workspace):
    from pillar_b_voice import speech

    assert not speech.stt_ready() and not speech.tts_ready()
    with pytest.raises(speech.SpeechUnavailable):
        speech.transcribe(b"x")
    with pytest.raises(speech.SpeechUnavailable):
        speech.synthesize("hi")


def test_stt_uses_groq_whisper_and_masks_pii(workspace, monkeypatch):
    from pillar_b_voice import speech

    monkeypatch.setenv("VOICE_STT_ENABLED", "true")
    monkeypatch.setenv("GROQ_API_KEY", "x")
    get_settings.cache_clear()
    seen = {}

    class Transcriptions:
        def create(self, **kw):
            seen.update(kw)
            return types.SimpleNamespace(text="book a call, my number is 9876543210")

    fake = types.SimpleNamespace(audio=types.SimpleNamespace(transcriptions=Transcriptions()))
    monkeypatch.setattr(speech, "_groq_client", lambda: fake)
    text = speech.transcribe(b"RIFF....", "a.wav")
    assert seen["model"] == "whisper-large-v3-turbo" and seen["language"] == "en"
    assert "9876543210" not in text and "[REDACTED]" in text

    def broken():
        raise TimeoutError

    monkeypatch.setattr(speech, "_groq_client", broken)
    with pytest.raises(speech.SpeechUnavailable):
        speech.transcribe(b"x")
    get_settings.cache_clear()


def test_tts_uses_edge_tts_voice(workspace, monkeypatch):
    from pillar_b_voice import speech

    monkeypatch.setenv("VOICE_TTS_ENABLED", "true")
    get_settings.cache_clear()
    used = {}

    class Communicate:
        def __init__(self, text, voice):
            used.update(text=text, voice=voice)

        async def stream(self):
            yield {"type": "audio", "data": b"ab"}
            yield {"type": "WordBoundary"}
            yield {"type": "audio", "data": b"c"}

    monkeypatch.setitem(sys.modules, "edge_tts", types.SimpleNamespace(Communicate=Communicate))
    assert speech.synthesize("N L dash A 1 2 3") == b"abc"
    assert used["voice"] == "en-IN-NeerjaNeural"
    get_settings.cache_clear()
