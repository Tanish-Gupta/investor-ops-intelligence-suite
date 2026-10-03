"""Shared fixtures. No test reaches a real LLM unless it is marked `llm_live`."""

from __future__ import annotations

import litellm
import pytest

from config.settings import get_settings


class _BlockedLLM(RuntimeError):
    pass


@pytest.fixture(autouse=True)
def _no_live_llm(request, monkeypatch):
    if request.node.get_closest_marker("llm_live"):
        yield
        return
    # Hermetic: ignore real keys in .env; tests that need a key set one explicitly.
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GROQ_API_KEY", "")
    get_settings.cache_clear()

    def _blocked(*_a, **_k):
        raise _BlockedLLM("real LLM call attempted in an offline test")

    monkeypatch.setattr(litellm, "completion", _blocked)
    monkeypatch.setattr(litellm, "transcription", _blocked)
    yield
    get_settings.cache_clear()


@pytest.fixture
def fresh_settings(monkeypatch):
    """Clear the settings cache before and after a test that changes env vars."""
    get_settings.cache_clear()
    yield monkeypatch
    get_settings.cache_clear()


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """Isolated data dir + SQLite DB so pulses, bookings and notes never touch real artifacts."""
    from core import state

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "artifacts" / "suite.db"))
    monkeypatch.setenv("PULSE_AUTOBUILD", "false")  # tests opt in explicitly
    get_settings.cache_clear()
    state.get_engine.cache_clear()
    yield tmp_path
    get_settings.cache_clear()
    state.get_engine.cache_clear()


@pytest.fixture
def with_key(monkeypatch):
    """Pretend a key exists (LLM calls themselves are mocked per test)."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")  # pragma: allowlist secret
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
