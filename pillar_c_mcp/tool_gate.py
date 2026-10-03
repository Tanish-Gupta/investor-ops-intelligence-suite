"""ToolGate (ported from M3 `mcp_client/tool_gate.py`): deterministic policy checked right before
every MCP write. It is code, not a prompt."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from core import pii
from core.state import ActionStatus

from .plan import EDITABLE_FIELDS, WRITE_TOOLS


@dataclass(frozen=True)
class GateDecision:
    approved: bool
    rule: str | None = None

    @property
    def label(self) -> str:
        return "approved" if self.approved else f"rejected:{self.rule}"


APPROVED = GateDecision(True)
RUNNABLE = {ActionStatus.APPROVED.value, ActionStatus.RETRYING.value}


def strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        return [s for v in value.values() for s in strings(v)]
    if isinstance(value, list | tuple):
        return [s for v in value for s in strings(v)]
    return []


def _fixed(args: Mapping[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in args.items() if k not in EDITABLE_FIELDS}


def check_job(
    tool: str, args: Mapping[str, Any], *, status: str, plan_args: Mapping[str, Any]
) -> GateDecision:
    """Known write tool, human-approved, no PII, and args equal to the plan (except edits)."""
    if tool not in WRITE_TOOLS:
        return GateDecision(False, "unknown_tool")
    if status not in RUNNABLE:
        return GateDecision(False, "not_approved")
    if any(pii.contains_pii(s) for s in strings(args)):
        return GateDecision(False, "pii")
    if _fixed(args) != _fixed(plan_args):
        return GateDecision(False, "plan_mismatch")
    return APPROVED
