"""System health + headline numbers for the Overview tab and sidebar (no LLM/network calls)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from config.settings import ROOT_DIR, get_settings
from core import state

REPORTS_DIR = ROOT_DIR / "evals" / "reports"
LATEST_EVAL = REPORTS_DIR / "eval_report_latest.json"


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool | None  # None = optional / degraded but usable
    detail: str


def _kb_check() -> Check:
    try:
        from pillar_a_kb.ingest import read_manifest

        m = read_manifest()
    except Exception as e:  # pragma: no cover - defensive
        return Check("Knowledge base index", False, f"unreadable ({type(e).__name__})")
    if not m:
        return Check(
            "Knowledge base index", False, "not built — use 🔎 Unified Search → Build index"
        )
    n = m.get("total_chunks") or len(m.get("documents", {}) or {})
    return Check("Knowledge base index", True, f"built ({n} chunks)" if n else "built")


def _models_check() -> Check:
    if get_settings().kb_lite:
        return Check("Embedding / reranker models", None, "lite runtime — keyword search only")
    d: Path = get_settings().models_dir
    ok = d.exists() and any(d.iterdir())
    detail = "cached locally" if ok else "missing — run scripts/download_models.py"
    return Check("Embedding / reranker models", ok, detail)


def _llm_check() -> Check:
    s = get_settings()
    keys = [n for n, k in (("Gemini", s.gemini_api_key), ("Groq", s.groq_api_key)) if k]
    toggles = {
        "RAG": s.rag_llm_enabled, "Pulse": s.pulse_llm_enabled, "Voice NLU": s.voice_llm_enabled,
        "Guard": s.guard_llm_enabled,
    }  # fmt: skip
    on = [n for n, v in toggles.items() if v]
    if not keys:
        return Check("LLM", None, "no API key — deterministic mode (rules + templates)")
    return Check("LLM", True, f"keys: {', '.join(keys)} · enabled for: {', '.join(on) or 'none'}")


def _mcp_check() -> Check:
    try:
        from pillar_c_mcp.client import get_client, run_sync

        tools = run_sync(get_client().declarations())
    except Exception as e:
        return Check("MCP tool server", False, f"offline: {type(e).__name__}: {str(e)[:80]}")
    mode = get_settings().adapter_mode
    return Check("MCP tool server", True, f"{len(tools)} tools · `{mode}` backends · no send tool")


def _pulse_check() -> Check:
    from pillar_b_voice.greeting import pulse_is_fresh
    from pillar_m2_pulse.pulse import get_latest_pulse

    p = get_latest_pulse()
    if p is None:
        return Check("Weekly Pulse", None, "none yet — generate one in 📊 Review Pulse")
    fresh = pulse_is_fresh(p)
    detail = f"{p.pulse_id} · top theme {p.top_theme}" + ("" if fresh else " · stale (> 14 d)")
    return Check("Weekly Pulse", True if fresh else None, detail)


def checks() -> list[Check]:
    return [_kb_check(), _models_check(), _llm_check(), _mcp_check(), _pulse_check()]


def last_eval() -> dict[str, Any] | None:
    if not LATEST_EVAL.exists():
        return None
    try:
        return json.loads(LATEST_EVAL.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def summary() -> dict[str, Any]:
    from pillar_m2_pulse.pulse import get_latest_pulse

    p = get_latest_pulse()
    bookings = state.list_bookings()
    acts = state.list_actions()
    return {
        "pulse_id": p.pulse_id if p else None,
        "top_theme": p.top_theme if p else None,
        "bookings": len(bookings),
        "pending_approvals": sum(a.status == "PENDING" for a in acts),
        "failed_actions": sum(a.status == "FAILED" for a in acts),
        "needs_attention": sum(b.status == "NEEDS_ATTENTION" for b in bookings),
    }
