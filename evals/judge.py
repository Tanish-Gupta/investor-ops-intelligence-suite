"""Optional LLM judge (opt-in: `EVAL_LLM_JUDGE=true` + an API key).

Each function returns a parsed verdict, or None when the judge is off or fails, so callers
always fall back to the deterministic proxies. The judge model (`LLM_JUDGE`) is a stronger model
than the generator and runs at temperature 0.
"""

from __future__ import annotations

import json
import logging
from typing import TypeVar

from pydantic import BaseModel, Field

from config.settings import get_settings
from core import llm
from core.prompts import load_prompt

_log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


class Claim(BaseModel):
    claim: str
    supported: bool
    reason: str = ""


class FaithfulnessVerdict(BaseModel):
    claims: list[Claim] = Field(default_factory=list)

    @property
    def score(self) -> float:
        return sum(c.supported for c in self.claims) / len(self.claims) if self.claims else 1.0


class RelevanceVerdict(BaseModel):
    answers_fact: float = Field(ge=0.0, le=1.0)
    answers_fee_scenario: float = Field(ge=0.0, le=1.0)
    on_topic: float = Field(ge=0.0, le=1.0)
    rationale: str = ""

    @property
    def score(self) -> float:
        return (self.answers_fact + self.answers_fee_scenario + self.on_topic) / 3


class ToneVerdict(BaseModel):
    tone: int = Field(ge=1, le=5)
    ideas_quality: int = Field(ge=1, le=5)
    rationale: str = ""


class RefusalVerdict(BaseModel):
    refused: bool
    gives_advice: bool
    leaks_pii: bool
    rationale: str = ""


def enabled() -> bool:
    s = get_settings()
    return s.eval_llm_judge and llm.llm_available(s)


def judge_label() -> str:
    return f"llm:{get_settings().llm_judge}" if enabled() else "deterministic"


def _ask(prompt: str, payload: dict, schema: type[T]) -> T | None:
    if not enabled():
        return None
    try:
        return llm.complete(
            load_prompt(prompt),
            json.dumps(payload, ensure_ascii=False, indent=1),
            schema=schema,
            model=get_settings().llm_judge,
            temperature=0.0,
        )
    except llm.LLMError as exc:
        _log.warning("eval_judge_failed", extra={"prompt": prompt, "error": str(exc)[:200]})
        return None


def faithfulness(
    question: str, bullets: list[str], chunks: list[str]
) -> FaithfulnessVerdict | None:
    payload = {"QUESTION": question, "ANSWER": bullets, "SOURCE CHUNKS": chunks}
    return _ask("eval_faithfulness.v1.md", payload, FaithfulnessVerdict)


def relevance(question: str, bullets: list[str], item: dict) -> RelevanceVerdict | None:
    payload = {
        "QUESTION": question,
        "ANSWER": bullets,
        "EXPECTED FACTS": item.get("expected_facts", []),
        "EXPECTED FEE POINTS": item.get("expected_fee_points", []),
    }
    return _ask("eval_relevance.v1.md", payload, RelevanceVerdict)


def pulse_tone(pulse_md: str) -> ToneVerdict | None:
    return _ask("eval_pulse_tone.v1.md", {"PULSE": pulse_md}, ToneVerdict)


def refusal(prompt: str, reply: str) -> RefusalVerdict | None:
    return _ask(
        "eval_refusal.v1.md", {"USER PROMPT": prompt, "ASSISTANT REPLY": reply}, RefusalVerdict
    )
