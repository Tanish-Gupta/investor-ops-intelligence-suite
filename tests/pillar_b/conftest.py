from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 10, 3, 10, 0, tzinfo=IST)  # Saturday; mock calendar starts Mon 5 Oct


def fixed_now() -> datetime:
    return NOW


@pytest.fixture
def make_session(workspace):
    from pillar_b_voice.agent import VoiceSession

    calls: list = []

    def _make(pulse=None, **kw):
        kw.setdefault("on_end", calls.append)
        s = VoiceSession(pulse=pulse, now=fixed_now, **kw)
        s.hook_calls = calls
        return s

    return _make


def run(session, *utterances):
    turns = [session.start()] if session.greeting is None else []
    turns += [session.handle(u) for u in utterances]
    return turns
