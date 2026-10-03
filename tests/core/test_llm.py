from types import SimpleNamespace

import litellm
import pytest
from pydantic import BaseModel, SecretStr

from core import llm


class Answer(BaseModel):
    answer: str
    score: int


def _resp(content):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
    )


@pytest.fixture
def fake_llm(monkeypatch):
    calls = []
    replies = []

    def completion(**kwargs):
        calls.append(kwargs)
        r = replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return _resp(r)

    monkeypatch.setattr(litellm, "completion", completion)
    monkeypatch.setattr(litellm, "completion_cost", lambda **_: 0.0001)
    return calls, replies


def test_text_completion(fake_llm):
    calls, replies = fake_llm
    replies.append("  hello  ")
    assert llm.complete("sys", "hi", model="m1", fallback="") == "hello"
    assert calls[0]["messages"][0] == {"role": "system", "content": "sys"}
    assert calls[0]["temperature"] == 0.0
    assert calls[0]["timeout"] > 0


def test_structured_output_validated(fake_llm):
    _, replies = fake_llm
    replies.append('```json\n{"answer": "ok", "score": 3}\n```')
    out = llm.complete("sys", "q", schema=Answer, model="m1", fallback="")
    assert out == Answer(answer="ok", score=3)


def test_invalid_output_retried_with_feedback(fake_llm):
    calls, replies = fake_llm
    replies.extend(['{"answer": "ok"}', '{"answer": "ok", "score": 1}'])
    usage = llm.LLMUsage(model="")
    out = llm.complete("sys", "q", schema=Answer, model="m1", fallback="", usage=usage)
    assert out.score == 1
    assert len(calls) == 2
    assert "did not match" in calls[1]["messages"][-1]["content"]
    assert usage.attempts == ["m1", "m1"] and usage.prompt_tokens == 10


def test_falls_back_to_second_model(fake_llm):
    calls, replies = fake_llm
    replies.extend([TimeoutError("slow"), '{"answer": "fb", "score": 2}'])
    out = llm.complete("sys", "q", schema=Answer, model="primary", fallback="secondary")
    assert out.answer == "fb"
    assert [c["model"] for c in calls] == ["primary", "secondary"]


def test_raises_after_all_failures(fake_llm):
    _, replies = fake_llm
    replies.extend(["not json", "still not json"])
    with pytest.raises(llm.LLMError):
        llm.complete("sys", "q", schema=Answer, model="m1", fallback="")


def test_api_key_passed_per_call(fake_llm, fresh_settings):
    calls, replies = fake_llm
    fresh_settings.setenv("GROQ_API_KEY", "gsk_unit_test")
    fresh_settings.delenv("GEMINI_API_KEY", raising=False)
    replies.append("x")
    llm.complete("s", "q", model="groq/some-model", fallback="")
    assert calls[0]["api_key"] == "gsk_unit_test"  # pragma: allowlist secret


def test_llm_available():
    base = llm.get_settings().model_copy(update={"gemini_api_key": None, "groq_api_key": None})
    assert not llm.llm_available(base)
    assert llm.llm_available(base.model_copy(update={"groq_api_key": SecretStr("k")}))


def test_offline_guard_blocks_real_calls():
    with pytest.raises(RuntimeError, match="offline"):
        litellm.completion(model="x", messages=[])
