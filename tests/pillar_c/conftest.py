from __future__ import annotations

import pytest

from tests.pillar_b.conftest import fixed_now, run

__all__ = ["fixed_now", "run"]


@pytest.fixture
def hitl(workspace):
    """Isolated workspace with fresh MCP backends (clean call counters)."""
    from pillar_c_mcp.client import get_bundle, reset_bundles

    reset_bundles()
    yield get_bundle()
    reset_bundles()


@pytest.fixture
def call(hitl):
    """Run one scripted voice call with the real end-of-call hook; returns the booking code."""
    from pillar_b_voice.agent import VoiceSession

    def _call(*utterances: str, pulse=None) -> str | None:
        s = VoiceSession(pulse=pulse, now=fixed_now)
        turns = run(s, *utterances)
        s.end()
        codes = [t.booking_code for t in turns if t.booking_code]
        return codes[-1] if codes else None

    return _call


def writes(bundle) -> int:
    """Number of backend writes so far (reads such as list_busy are excluded)."""
    cal = sum(n for k, n in bundle.calendar.calls.items() if k != "list_busy")
    return cal + sum(bundle.docs.calls.values()) + sum(bundle.gmail.calls.values())
