"""Optional voice I/O for the Voice tab: Groq Whisper STT and edge-tts playback.

Both are opt-in (`VOICE_STT_ENABLED`, `VOICE_TTS_ENABLED`) because they call external services.
The agent itself is text-in/text-out, so the tab always works with typed input."""

from __future__ import annotations

import logging
from typing import Any

from config.settings import get_settings
from core import pii

_log = logging.getLogger(__name__)


class SpeechUnavailable(RuntimeError):
    """Voice I/O is switched off, unconfigured, or the provider failed."""


def stt_ready() -> bool:
    s = get_settings()
    return bool(s.voice_stt_enabled and s.groq_api_key)


def tts_ready() -> bool:
    return bool(get_settings().voice_tts_enabled)


def _groq_client() -> Any:
    from groq import Groq

    s = get_settings()
    return Groq(api_key=s.groq_api_key.get_secret_value(), timeout=s.llm_timeout_s)  # type: ignore[union-attr]


def transcribe(audio: bytes, filename: str = "call.wav") -> str:
    """Speech → text (English, Indian accents handled by Whisper); PII is masked before return."""
    if not stt_ready():
        raise SpeechUnavailable("speech input is off (set VOICE_STT_ENABLED and GROQ_API_KEY)")
    if not audio:
        raise SpeechUnavailable("no audio received")
    model = get_settings().stt_model.removeprefix("groq/")
    try:
        res = _groq_client().audio.transcriptions.create(
            file=(filename, audio), model=model, language="en", temperature=0.0
        )
    except Exception as e:  # provider/network errors → typed fallback to text input
        _log.warning("stt_failed", extra={"error": type(e).__name__})
        raise SpeechUnavailable(f"speech-to-text failed ({type(e).__name__})") from e
    text = (getattr(res, "text", None) or "").strip()
    return pii.redact(text) if text else ""


async def _synthesize(text: str, voice: str) -> bytes:
    import edge_tts

    chunks: list[bytes] = []
    async for part in edge_tts.Communicate(text, voice).stream():
        if part.get("type") == "audio":
            chunks.append(part["data"])
    return b"".join(chunks)


def synthesize(text: str) -> bytes:
    """Text → MP3 bytes with the configured en-IN neural voice."""
    if not tts_ready():
        raise SpeechUnavailable("spoken replies are off (set VOICE_TTS_ENABLED)")
    try:
        from pillar_c_mcp.client import run_sync  # loop-safe (Streamlit / tests)

        return run_sync(_synthesize(text, get_settings().tts_voice))
    except Exception as e:
        _log.warning("tts_failed", extra={"error": type(e).__name__})
        raise SpeechUnavailable(f"text-to-speech failed ({type(e).__name__})") from e
