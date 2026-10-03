"""Single LLM gateway (LiteLLM) for every pillar.

- Primary → fallback model chain (rules L1/L2), explicit timeout, temperature 0 by default.
- Structured output: pass a Pydantic model as `schema`; the reply is validated and, on a
  validation error, retried once with the error fed back (rule L6). A second failure raises
  `LLMError` so callers can use their deterministic fallback.
- API keys are passed per call from `Settings` (never written to the process environment).
- Token usage / cost is logged without prompt or completion text (rule P6).
- Optional Arize Phoenix tracing (`PHOENIX_TRACING=true`) with inputs/outputs hidden.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, TypeVar, overload

import litellm
from pydantic import BaseModel, ValidationError

from config.settings import Settings, get_settings

_log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


_KEYED_PROVIDERS = {"gemini", "groq"}


class LLMError(RuntimeError):
    """All models failed, or the structured reply was invalid after the retry."""


@dataclass
class LLMUsage:
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    latency_s: float = 0.0
    attempts: list[str] = field(default_factory=list)


def _api_key_for(model: str, settings: Settings) -> str | None:
    provider = model.split("/", 1)[0].lower()
    secret = {"gemini": settings.gemini_api_key, "groq": settings.groq_api_key}.get(provider)
    return secret.get_secret_value() if secret else None


def _needs_key(model: str) -> bool:
    return model.split("/", 1)[0].lower() in _KEYED_PROVIDERS


def _model_chain(model: str | None, fallback: str | None, settings: Settings) -> list[str]:
    chain = [model or settings.llm_primary]
    fb = settings.llm_fallback if fallback is None else fallback
    if fb and fb not in chain:
        chain.append(fb)
    return chain


def _parse_json(text: str) -> Any:
    return json.loads(_FENCE_RE.sub("", text or "").strip())


def _content(response: Any) -> str:
    return response.choices[0].message.content or ""


def _record_usage(response: Any, model: str, started: float, usage: LLMUsage) -> None:
    u = getattr(response, "usage", None)
    usage.model = model
    usage.prompt_tokens = int(getattr(u, "prompt_tokens", 0) or 0)
    usage.completion_tokens = int(getattr(u, "completion_tokens", 0) or 0)
    usage.latency_s = round(time.monotonic() - started, 3)
    try:
        usage.cost_usd = float(litellm.completion_cost(completion_response=response) or 0.0)
    except Exception:  # unknown pricing is not an error
        usage.cost_usd = 0.0
    _log.info(
        "llm_call",
        extra={
            "model": model,
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
            "cost_usd": usage.cost_usd,
            "latency_s": usage.latency_s,
        },
    )


def _call(
    model: str,
    messages: list[dict[str, str]],
    *,
    schema: type[BaseModel] | None,
    temperature: float,
    max_tokens: int | None,
    settings: Settings,
) -> Any:
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "timeout": settings.llm_timeout_s,
        "num_retries": 0,
    }
    if max_tokens:
        kwargs["max_tokens"] = max_tokens
    if schema is not None:
        kwargs["response_format"] = schema
    key = _api_key_for(model, settings)
    if key:
        kwargs["api_key"] = key
    return litellm.completion(**kwargs)


@overload
def complete(
    system: str,
    messages: str | Sequence[dict[str, str]],
    *,
    schema: type[T],
    model: str | None = ...,
    fallback: str | None = ...,
    temperature: float = ...,
    max_tokens: int | None = ...,
    usage: LLMUsage | None = ...,
) -> T: ...


@overload
def complete(
    system: str,
    messages: str | Sequence[dict[str, str]],
    *,
    schema: None = ...,
    model: str | None = ...,
    fallback: str | None = ...,
    temperature: float = ...,
    max_tokens: int | None = ...,
    usage: LLMUsage | None = ...,
) -> str: ...


def complete(
    system: str,
    messages: str | Sequence[dict[str, str]],
    *,
    schema: type[BaseModel] | None = None,
    model: str | None = None,
    fallback: str | None = None,
    temperature: float = 0.0,
    max_tokens: int | None = None,
    usage: LLMUsage | None = None,
) -> Any:
    """Run a chat completion. Returns a validated `schema` instance, or text when no schema.

    `messages` may be a single user string or a list of {"role", "content"} dicts.
    `fallback=""` disables the fallback model.
    """
    settings = get_settings()
    usage = usage or LLMUsage(model="")
    convo = [{"role": "user", "content": messages}] if isinstance(messages, str) else list(messages)
    base = [{"role": "system", "content": system}, *convo]
    errors: list[str] = []

    for model_name in _model_chain(model, fallback, settings):
        if _needs_key(model_name) and not _api_key_for(model_name, settings):
            # never let LiteLLM fall back to ambient env keys
            errors.append(f"{model_name}: no API key configured")
            continue
        msgs = list(base)
        for attempt in range(2):  # 1 call + 1 corrective retry for invalid structured output
            usage.attempts.append(model_name)
            started = time.monotonic()
            try:
                response = _call(
                    model_name,
                    msgs,
                    schema=schema,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    settings=settings,
                )
            except Exception as exc:  # provider/network/timeout → next model
                errors.append(f"{model_name}: {type(exc).__name__}")
                _log.warning("llm_error", extra={"model": model_name, "error": type(exc).__name__})
                break
            _record_usage(response, model_name, started, usage)
            text = _content(response)
            if schema is None:
                if text.strip():
                    return text.strip()
                errors.append(f"{model_name}: empty reply")
                break
            try:
                return schema.model_validate(_parse_json(text))
            except (ValidationError, json.JSONDecodeError, TypeError) as exc:
                errors.append(f"{model_name}: invalid output ({type(exc).__name__})")
                if attempt == 0:
                    msgs = [
                        *base,
                        {"role": "assistant", "content": text},
                        {
                            "role": "user",
                            "content": "Your reply did not match the required JSON schema: "
                            f"{_short_error(exc)}. Reply again with ONLY valid JSON for "
                            f"this schema: {json.dumps(schema.model_json_schema())}",
                        },
                    ]
    raise LLMError("; ".join(errors) or "no model configured")


def _short_error(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()[:5])
    return str(exc)[:200]


def llm_available(settings: Settings | None = None) -> bool:
    """True when at least one configured model has an API key."""
    s = settings or get_settings()
    return any(_api_key_for(m, s) for m in _model_chain(None, None, s))


_tracing_on = False


def setup_tracing() -> bool:
    """Enable Phoenix/OpenInference tracing for LiteLLM when PHOENIX_TRACING=true."""
    global _tracing_on
    if _tracing_on or not get_settings().phoenix_tracing:
        return _tracing_on
    os.environ.setdefault("OPENINFERENCE_HIDE_INPUTS", "true")  # P6: no prompt text in traces
    os.environ.setdefault("OPENINFERENCE_HIDE_OUTPUTS", "true")
    from openinference.instrumentation.litellm import LiteLLMInstrumentor
    from phoenix.otel import register

    LiteLLMInstrumentor().instrument(tracer_provider=register(project_name="investor-ops-suite"))
    _tracing_on = True
    return True
