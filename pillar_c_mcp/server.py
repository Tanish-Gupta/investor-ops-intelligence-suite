"""The FastMCP server (ported from M3 `mcp_server/server.py`): five tools, nothing else.

Run standalone (the app connects over stdio or HTTP):
    uv run python -m pillar_c_mcp.server                         # stdio
    uv run python -m pillar_c_mcp.server --transport http --port 8001
or in-process with `MCP_SERVER_TARGET=inprocess` (the default; still spoken to over MCP).

Errors are raised as `ToolError("retryable:…")` (timeouts, 408/429/5xx, I/O) or
`ToolError("permanent:…")` so the outbox knows whether to back off and retry.
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any, Literal, TypeVar

from pydantic import Field

from core import guardrails, pii

from .plan import (
    CODE_PATTERN,
    EVENT_ID_PATTERN,
    IST_PATTERN,
    MAX_MARKET_CONTEXT,
    MAX_SUMMARY,
)

T = TypeVar("T")

IstDateTime = Annotated[
    str,
    Field(description="ISO-8601 datetime with the IST offset, e.g. 2026-10-06T15:00:00+05:30",
          pattern=IST_PATTERN),
]  # fmt: skip
Code = Annotated[
    str, Field(description="Booking code exactly as issued, e.g. NL-A742", pattern=CODE_PATTERN)
]
PulseId = Annotated[
    str | None,
    Field(description="Weekly Pulse id, e.g. PULSE-2026-W40", pattern=r"^PULSE-\d{4}-W\d{2}$"),
]
Slot = Annotated[
    str, Field(description="Human slot, e.g. 'Tue, 6 Oct, 3:00 PM IST'", max_length=80)
]
TopicName = Literal[
    "KYC/Onboarding",
    "SIP/Mandates",
    "Statements/Tax Docs",
    "Withdrawals & Timelines",
    "Nominee Updates",
    "Account & App Access",
]
TemplateName = Literal["booking", "reschedule", "cancel", "waitlist", "ops_alert"]
NoteStatus = Literal["tentative", "waitlist", "rescheduled", "cancelled", "hold_failed"]

SERVER_NAME = "investor-ops-tools"


def _topic_names() -> tuple[str, ...]:
    return TopicName.__args__  # type: ignore[attr-defined]


def _http_status(e: BaseException) -> int | None:
    resp = getattr(e, "resp", None)
    status = getattr(resp, "status", None)
    return int(status) if status is not None else None


def _check_no_pii(args: dict[str, Any]) -> None:
    from fastmcp.exceptions import ToolError

    for value in args.values():
        if isinstance(value, str) and pii.contains_pii(value):
            raise ToolError("permanent:pii - personal data is not accepted by these tools")


def _check_no_advice(*texts: str | None) -> None:
    from fastmcp.exceptions import ToolError

    for text in texts:
        if text and guardrails.output_violations(text):
            raise ToolError("permanent:guardrail - advice language is not allowed in drafts")


async def _run(fn: Callable[[], T]) -> T:
    """Run a blocking backend call off the event loop and classify its errors."""
    from fastmcp.exceptions import ToolError

    try:
        return await asyncio.to_thread(fn)
    except ToolError:
        raise
    except Exception as e:
        status = _http_status(e)
        if status is not None:
            kind = "retryable" if status in (408, 429) or status >= 500 else "permanent"
            raise ToolError(f"{kind}:{status} google api error") from e
        if isinstance(e, TimeoutError | OSError):
            raise ToolError(f"retryable:{type(e).__name__}") from e
        if isinstance(e, ValueError | KeyError):
            raise ToolError(f"permanent:{e}") from e
        raise ToolError(f"retryable:{type(e).__name__}") from e


def build_server(calendar: Any, docs: Any, gmail: Any) -> Any:
    """FastMCP server over injected backends (local files or Google wrappers)."""
    from fastmcp import FastMCP

    mcp = FastMCP(
        name=SERVER_NAME,
        instructions=(
            "Back-office tools for tentative advisor pre-bookings. Every write runs only after "
            "a human approved it in the HITL Approval Center. Calendar holds are tentative; "
            "email is only ever drafted, never sent."
        ),
    )

    @mcp.tool()
    async def calendar_list_busy(start_ist: IstDateTime, end_ist: IstDateTime) -> dict[str, Any]:
        """Return the busy intervals of the advisor calendar between start and end (IST)."""
        _check_no_pii({"start_ist": start_ist, "end_ist": end_ist})
        busy = await _run(lambda: calendar.list_busy(start_ist, end_ist))
        return {"busy": busy}

    @mcp.tool()
    async def calendar_create_hold(
        code: Code,
        topic: TopicName,
        start_ist: IstDateTime,
        end_ist: IstDateTime,
        kind: Literal["booking", "waitlist"] = "booking",
        version: Annotated[int, Field(ge=1, le=99)] = 1,
    ) -> dict[str, Any]:
        """Create the tentative hold 'Advisor Q&A — {topic} — {code}' (idempotent per version)."""
        _check_no_pii({"code": code, "topic": topic, "start_ist": start_ist, "end_ist": end_ist})
        return await _run(
            lambda: calendar.create_hold(
                code=code, topic=topic, start_ist=start_ist, end_ist=end_ist, kind=kind,
                version=version,
            )
        )  # fmt: skip

    @mcp.tool()
    async def calendar_delete_hold(
        event_id: Annotated[
            str, Field(description="Calendar event id of the hold", pattern=EVENT_ID_PATTERN)
        ],
    ) -> dict[str, Any]:
        """Release a tentative hold (idempotent: an already deleted hold counts as deleted)."""
        _check_no_pii({"event_id": event_id})
        deleted = await _run(lambda: calendar.delete_hold(event_id))
        return {"deleted": deleted, "event_id": event_id}

    @mcp.tool()
    async def docs_append_prebooking(
        date: Annotated[
            str, Field(description="Booking date YYYY-MM-DD (IST)", pattern=r"^\d{4}-\d{2}-\d{2}$")
        ],
        topic: TopicName,
        slot: Slot,
        code: Code,
        status: NoteStatus,
        pulse_id: PulseId = None,
    ) -> dict[str, Any]:
        """Append '{date} | {topic} | {slot} | {code} | {status} | {pulse_id}' to the notes doc."""
        _check_no_pii({"date": date, "topic": topic, "slot": slot, "code": code,
                       "pulse_id": pulse_id})  # fmt: skip
        return await _run(
            lambda: docs.append_prebooking(
                date=date, topic=topic, slot=slot, code=code, status=status, pulse_id=pulse_id
            )
        )

    @mcp.tool()
    async def gmail_create_draft(
        template: TemplateName,
        code: Code,
        topic: TopicName,
        slot: Annotated[str | None, Field(description="Human slot", max_length=80)] = None,
        call_summary: Annotated[str | None, Field(max_length=MAX_SUMMARY)] = None,
        market_context: Annotated[str | None, Field(max_length=MAX_MARKET_CONTEXT)] = None,
        pulse_id: PulseId = None,
    ) -> dict[str, Any]:
        """Create (never send) the advisor email draft from a fixed template with Market Context."""
        _check_no_pii({"template": template, "code": code, "topic": topic, "slot": slot,
                       "call_summary": call_summary, "market_context": market_context,
                       "pulse_id": pulse_id})  # fmt: skip
        _check_no_advice(call_summary, market_context)
        return await _run(
            lambda: gmail.create_draft(
                template=template, code=code, topic=topic, slot=slot, call_summary=call_summary,
                market_context=market_context, pulse_id=pulse_id,
            )
        )  # fmt: skip

    return mcp


class GoogleConfigError(RuntimeError):
    pass


@dataclass
class Bundle:
    """A built server plus its backends (exposed so the UI/tests can read call counters)."""

    server: Any
    calendar: Any
    docs: Any
    gmail: Any
    mode: str


def build_bundle(settings: Any) -> Bundle:
    if settings.adapter_mode == "google":
        from .google import GoogleCalendar, GoogleDocs, GoogleGmail
        from .google.auth import build_services, load_credentials

        if not settings.google_prebooking_doc_id:
            raise GoogleConfigError("GOOGLE_PREBOOKING_DOC_ID is not set")
        if not settings.advisor_email:
            raise GoogleConfigError("ADVISOR_EMAIL is not set")
        creds = load_credentials(
            token_file=settings.google_token_path,
            service_account_file=settings.google_service_account_file,
        )
        cal_svc, docs_svc, gmail_svc = build_services(creds)
        cal = GoogleCalendar(cal_svc, settings.google_calendar_id)
        doc = GoogleDocs(docs_svc, settings.google_prebooking_doc_id)
        mail = GoogleGmail(gmail_svc, settings.advisor_email)
    else:
        from .local import LocalCalendar, LocalDocs, LocalGmail

        cal = LocalCalendar(settings.artifacts_dir)
        doc = LocalDocs()
        mail = LocalGmail(settings.artifacts_dir, settings.advisor_email)
    return Bundle(build_server(cal, doc, mail), cal, doc, mail, settings.adapter_mode)


def build_server_from_settings(settings: Any) -> Any:
    return build_bundle(settings).server


def main(argv: list[str] | None = None) -> None:
    from config.settings import get_settings

    parser = argparse.ArgumentParser(description="Investor Ops tools (FastMCP server)")
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args(argv)

    mcp = build_server_from_settings(get_settings())
    if args.transport == "http":
        mcp.run(transport="http", host=args.host, port=args.port)
    else:
        mcp.run()


if __name__ == "__main__":
    main()
